"""Merge reviewed Label Studio rectangles into a new YOLO training dataset.

Only approved bounding boxes from the ContextRico annotation queue are copied
into train/validation.  The original test split is copied without alteration.
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE_DATASET = PROJECT_ROOT / "data" / "visual_dataset"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "visual_dataset_reviewed"
SOURCE_ROOT = (PROJECT_ROOT / "data" / "external_sources" / "contextrico" / "extracted" / "ContextRico-DP").resolve()
CLASS_NAMES = [
    "ACTIVITY MESSAGE", "ATTENTION DISTRACTION", "COUNTDOWN TIMER", "DEFAULT CHOICE", "DISGUISED ADS",
    "GAMIFICATION", "HIGH DEMAND MESSAGE", "LIMITED TIME MESSAGE", "LOW STOCK MESSAGE", "NAGGING",
]
CLASS_IDS = {name: index for index, name in enumerate(CLASS_NAMES)}


def yolo_line(value: dict, width: int, height: int) -> str | None:
    labels = value.get("rectanglelabels", [])
    if len(labels) != 1 or labels[0] not in CLASS_IDS:
        return None
    x, y, box_w, box_h = (float(value[key]) for key in ("x", "y", "width", "height"))
    if box_w <= 0 or box_h <= 0 or x < 0 or y < 0 or x + box_w > 100 or y + box_h > 100:
        return None
    # Label Studio rectangle values are percentages of the original image.
    center_x = (x + box_w / 2) / 100
    center_y = (y + box_h / 2) / 100
    return f"{CLASS_IDS[labels[0]]} {center_x:.6f} {center_y:.6f} {box_w / 100:.6f} {box_h / 100:.6f}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path, help="Label Studio JSON export.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"Output already exists: {output}. Choose a new --output path.")

    exported_tasks = json.loads(args.export.read_text(encoding="utf-8"))
    shutil.copytree(BASE_DATASET, output)
    accepted, skipped, category_counts = 0, 0, Counter()
    for task in exported_tasks:
        data = task.get("data", {})
        split = data.get("split")
        task_id = data.get("task_id")
        image_ref = data.get("image", "")
        if split not in {"train", "valid"} or not task_id or not image_ref.startswith("/data/local-files/?d="):
            skipped += 1
            continue
        relative = image_ref.removeprefix("/data/local-files/?d=")
        source_image = (PROJECT_ROOT / relative).resolve()
        if SOURCE_ROOT not in source_image.parents or not source_image.is_file():
            skipped += 1
            continue
        annotations = task.get("annotations", [])
        completed = next((item for item in reversed(annotations) if not item.get("was_cancelled", False)), None)
        if not completed:
            skipped += 1
            continue
        lines = []
        for result in completed.get("result", []):
            if result.get("type") != "rectanglelabels":
                continue
            line = yolo_line(result.get("value", {}), int(result.get("original_width", 0)), int(result.get("original_height", 0)))
            if line:
                lines.append(line)
                category_counts[CLASS_NAMES[int(line.split()[0])]] += 1
        # Completed no-cue reviews become background images; incomplete tasks do not enter the dataset.
        if not lines and not any(r.get("value", {}).get("choices") == ["no_compatible_cue"] for r in completed.get("result", [])):
            skipped += 1
            continue
        filename = f"contextrico_{task_id}{source_image.suffix.lower()}"
        destination_image = output / split / "images" / filename
        destination_label = output / split / "labels" / f"contextrico_{task_id}.txt"
        shutil.copy2(source_image, destination_image)
        if lines:
            destination_label.write_text("\n".join(lines) + "\n", encoding="utf-8")
        accepted += 1

    data_yaml = yaml.safe_load((BASE_DATASET / "data.yaml").read_text(encoding="utf-8"))
    data_yaml["path"] = str(output)
    (output / "data.yaml").write_text(yaml.safe_dump(data_yaml, sort_keys=False), encoding="utf-8")
    summary = {"accepted_tasks": accepted, "skipped_tasks": skipped, "boxes_by_category": category_counts,
               "source": "ContextRico-DP (CC BY 4.0)", "test_split": "Copied unchanged from visual_dataset"}
    (output / "import_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
