"""Create source-label-constrained OCR + YOLO box proposals.

The script calibrates per-class detector thresholds on the existing validation
set, removes perceptual duplicates of every existing dataset image, and merges
YOLO locations with the conservative OCR proposals. Outputs remain explicitly
machine-generated and are suitable for review or gated pseudo-label training.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
YOLO_CONFIG_ROOT = PROJECT_ROOT / "runtime_data" / "ultralytics"
MATPLOTLIB_CONFIG_ROOT = PROJECT_ROOT / "runtime_data" / "matplotlib"
YOLO_CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
MATPLOTLIB_CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("YOLO_CONFIG_DIR", str(YOLO_CONFIG_ROOT))
os.environ.setdefault("MPLCONFIGDIR", str(MATPLOTLIB_CONFIG_ROOT))

import torch
from ultralytics import YOLO


BASE_DATASET = PROJECT_ROOT / "data" / "visual_dataset"
DEFAULT_TASKS = PROJECT_ROOT / "data" / "annotation_queue" / "contextrico" / "tasks_with_machine_proposals.json"
DEFAULT_MODEL = PROJECT_ROOT / "model_artifacts" / "dark_pattern_yolo_v1" / "best.pt"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "annotation_queue" / "contextrico" / "tasks_with_max_proposals.json"
CLASS_NAMES = [
    "ACTIVITY MESSAGE", "ATTENTION DISTRACTION", "COUNTDOWN TIMER", "DEFAULT CHOICE", "DISGUISED ADS",
    "GAMIFICATION", "HIGH DEMAND MESSAGE", "LIMITED TIME MESSAGE", "LOW STOCK MESSAGE", "NAGGING",
]


def perceptual_hash(path: Path) -> int:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"Cannot read image: {path}")
    resized = cv2.resize(image, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    coefficients = cv2.dct(resized)[:8, :8]
    median = float(np.median(coefficients.flat[1:]))
    return sum(1 << index for index, value in enumerate(coefficients.flat) if value > median)


def yolo_labels(path: Path) -> list[tuple[int, np.ndarray]]:
    if not path.exists():
        return []
    labels = []
    for line in path.read_text(encoding="utf-8").splitlines():
        values = line.split()
        if len(values) != 5:
            continue
        class_id, cx, cy, width, height = int(values[0]), *(float(x) for x in values[1:])
        labels.append((class_id, np.array([cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2])))
    return labels


def iou(first: np.ndarray, second: np.ndarray) -> float:
    left_top = np.maximum(first[:2], second[:2])
    right_bottom = np.minimum(first[2:], second[2:])
    intersection = float(np.prod(np.maximum(0, right_bottom - left_top)))
    area_first = float(np.prod(np.maximum(0, first[2:] - first[:2])))
    area_second = float(np.prod(np.maximum(0, second[2:] - second[:2])))
    return intersection / max(area_first + area_second - intersection, 1e-9)


def calibrate(model: YOLO, device: int | str) -> tuple[dict[int, float], dict]:
    image_paths = sorted((BASE_DATASET / "valid" / "images").glob("*"))
    ground_truth = {}
    for image in image_paths:
        ground_truth[image.name] = yolo_labels(BASE_DATASET / "valid" / "labels" / f"{image.stem}.txt")
    predictions: dict[str, list[tuple[int, float, np.ndarray]]] = defaultdict(list)
    results = model.predict([str(path) for path in image_paths], conf=0.01, iou=0.5, imgsz=640, device=device, verbose=False)
    for path, result in zip(image_paths, results):
        present_classes = {class_id for class_id, _ in ground_truth[path.name]}
        width, height = result.orig_shape[1], result.orig_shape[0]
        scale = np.array([width, height, width, height], dtype=float)
        for box in result.boxes:
            class_id = int(box.cls.item())
            if class_id not in present_classes:
                continue
            predictions[path.name].append((class_id, float(box.conf.item()), box.xyxy[0].cpu().numpy() / scale))

    thresholds, metrics = {}, {}
    for class_id, class_name in enumerate(CLASS_NAMES):
        support = sum(1 for labels in ground_truth.values() for candidate, _ in labels if candidate == class_id)
        best = None
        for threshold in np.arange(0.05, 0.76, 0.05):
            true_positive = false_positive = 0
            for image_name, labels in ground_truth.items():
                truths = [box for candidate, box in labels if candidate == class_id]
                candidates = sorted(
                    [(score, box) for candidate, score, box in predictions[image_name] if candidate == class_id and score >= threshold],
                    reverse=True, key=lambda item: item[0],
                )
                matched = set()
                for _, predicted in candidates:
                    matches = [(iou(predicted, truth), index) for index, truth in enumerate(truths) if index not in matched]
                    overlap, index = max(matches, default=(0.0, -1))
                    if overlap >= 0.5:
                        true_positive += 1
                        matched.add(index)
                    else:
                        false_positive += 1
            precision = true_positive / max(true_positive + false_positive, 1)
            recall = true_positive / max(support, 1)
            beta_sq = 0.25
            f_half = (1 + beta_sq) * precision * recall / max(beta_sq * precision + recall, 1e-9)
            candidate = (f_half, precision, recall, -float(threshold))
            if best is None or candidate > best[0]:
                best = (candidate, float(threshold), precision, recall)
        chosen = best[1] if support and best and best[0][0] > 0 else 0.35
        thresholds[class_id] = max(0.10, chosen)
        metrics[class_name] = {
            "threshold": round(thresholds[class_id], 2), "support": support,
            "precision_at_iou_50": round(best[2], 3) if support and best else 0.0,
            "recall_at_iou_50": round(best[3], 3) if support and best else 0.0,
        }
    return thresholds, metrics


def result_box(class_name: str, xyxy: np.ndarray, width: int, height: int, score: float, source: str) -> dict:
    x1, y1, x2, y2 = (float(value) for value in xyxy)
    return {
        "from_name": "label", "to_name": "image", "type": "rectanglelabels",
        "original_width": width, "original_height": height, "image_rotation": 0,
        "score": round(score, 4), "meta": {"proposal_source": source},
        "value": {
            "x": round(x1 / width * 100, 3), "y": round(y1 / height * 100, 3),
            "width": round((x2 - x1) / width * 100, 3), "height": round((y2 - y1) / height * 100, 3),
            "rotation": 0, "rectanglelabels": [class_name],
        },
    }


def absolute_box(result: dict) -> np.ndarray:
    value = result["value"]
    width, height = result["original_width"], result["original_height"]
    x1, y1 = value["x"] / 100 * width, value["y"] / 100 * height
    return np.array([x1, y1, x1 + value["width"] / 100 * width, y1 + value["height"] / 100 * height])


def merge_boxes(ocr_boxes: list[dict], yolo_boxes: list[dict]) -> list[dict]:
    merged = list(yolo_boxes)
    for ocr in ocr_boxes:
        label = ocr["value"]["rectanglelabels"][0]
        if any(label == candidate["value"]["rectanglelabels"][0] and iou(absolute_box(ocr), absolute_box(candidate)) >= 0.25 for candidate in merged):
            continue
        ocr["score"] = 0.90
        ocr["meta"] = {"proposal_source": "ocr-rule"}
        merged.append(ocr)
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", default="0")
    parser.add_argument("--duplicate-distance", type=int, default=8)
    args = parser.parse_args()

    tasks = json.loads(args.tasks.read_text(encoding="utf-8"))
    base_hashes = []
    for split in ("train", "valid", "test"):
        for image in (BASE_DATASET / split / "images").glob("*"):
            if image.suffix.lower() in {".jpg", ".jpeg", ".png"}:
                base_hashes.append((split, perceptual_hash(image)))
    unique_tasks, excluded = [], Counter()
    for task in tasks:
        relative = task["data"]["image"].removeprefix("/data/local-files/?d=")
        image_hash = perceptual_hash(PROJECT_ROOT / relative)
        nearest = min(((image_hash ^ known_hash).bit_count(), split) for split, known_hash in base_hashes)
        if nearest[0] <= args.duplicate_distance:
            task["data"]["excluded_reason"] = f"perceptual duplicate of existing {nearest[1]} image"
            task.pop("predictions", None)
            excluded[nearest[1]] += 1
        else:
            unique_tasks.append(task)

    model = YOLO(str(args.model))
    thresholds, calibration = calibrate(model, args.device)
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    proposal_counts, tasks_with_boxes = Counter(), 0
    for task in unique_tasks:
        path = PROJECT_ROOT / task["data"]["image"].removeprefix("/data/local-files/?d=")
        prediction = model.predict(str(path), conf=0.05, iou=0.45, imgsz=640, batch=1,
                                   device=args.device, verbose=False)[0]
        allowed = set(task["data"]["source_labels"].split(", "))
        yolo_boxes = []
        for box in prediction.boxes:
            class_id, score = int(box.cls.item()), float(box.conf.item())
            class_name = CLASS_NAMES[class_id]
            if class_name not in allowed or score < thresholds[class_id]:
                continue
            yolo_boxes.append(result_box(class_name, box.xyxy[0].cpu().numpy(), prediction.orig_shape[1], prediction.orig_shape[0], score, "yolo-v1"))
        ocr_boxes = task.get("predictions", [{}])[0].get("result", []) if task.get("predictions") else []
        boxes = merge_boxes(ocr_boxes, yolo_boxes)
        if boxes:
            tasks_with_boxes += 1
            for box in boxes:
                proposal_counts[box["value"]["rectanglelabels"][0]] += 1
            task["predictions"] = [{"model_version": "source-constrained-ocr-yolo-v2", "score": 0.75, "result": boxes}]
        else:
            task.pop("predictions", None)

    args.output.write_text(json.dumps(tasks, indent=2), encoding="utf-8")
    summary = {
        "total_tasks": len(tasks), "unique_tasks": len(unique_tasks), "excluded_near_duplicates": dict(excluded),
        "tasks_with_proposals": tasks_with_boxes, "proposal_counts": dict(proposal_counts), "calibration": calibration,
        "warning": "Machine proposals; evaluate retrained weights on the unchanged real test split before deployment.",
    }
    summary_path = args.output.with_name("max_proposal_summary.json")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "calibration"}, indent=2))
    print(f"Calibration and full summary: {summary_path}")


if __name__ == "__main__":
    main()
