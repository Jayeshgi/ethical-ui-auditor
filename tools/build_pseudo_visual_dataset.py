"""Build a leakage-safe YOLO dataset from calibrated machine proposals.

Every new proposal is placed in training. Existing validation and test splits
remain unchanged and real-labelled, so model selection and final comparison do
not evaluate against pseudo labels.
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
DEFAULT_TASKS = PROJECT_ROOT / "data" / "annotation_queue" / "contextrico" / "tasks_with_max_proposals.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "visual_dataset_pseudo_v2"
CLASS_NAMES = [
    "ACTIVITY MESSAGE", "ATTENTION DISTRACTION", "COUNTDOWN TIMER", "DEFAULT CHOICE", "DISGUISED ADS",
    "GAMIFICATION", "HIGH DEMAND MESSAGE", "LIMITED TIME MESSAGE", "LOW STOCK MESSAGE", "NAGGING",
]
CLASS_IDS = {name: index for index, name in enumerate(CLASS_NAMES)}


def yolo_line(result: dict) -> str | None:
    value = result.get("value", {})
    labels = value.get("rectanglelabels", [])
    if len(labels) != 1 or labels[0] not in CLASS_IDS:
        return None
    x, y, width, height = (float(value.get(key, 0)) for key in ("x", "y", "width", "height"))
    if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > 100.01 or y + height > 100.01:
        return None
    return (f"{CLASS_IDS[labels[0]]} {(x + width / 2) / 100:.6f} {(y + height / 2) / 100:.6f} "
            f"{width / 100:.6f} {height / 100:.6f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"Output already exists: {output}. Choose another --output path.")
    shutil.copytree(BASE_DATASET, output)

    tasks = json.loads(args.tasks.read_text(encoding="utf-8"))
    image_count, box_counts = 0, Counter()
    for task in tasks:
        if task.get("data", {}).get("excluded_reason") or not task.get("predictions"):
            continue
        results = task["predictions"][0].get("result", [])
        lines = []
        for result in results:
            line = yolo_line(result)
            if line:
                lines.append(line)
                box_counts[CLASS_NAMES[int(line.split()[0])]] += 1
        if not lines:
            continue
        relative = task["data"]["image"].removeprefix("/data/local-files/?d=")
        source = (PROJECT_ROOT / relative).resolve()
        task_id = task["data"]["task_id"]
        image_name = f"pseudo_contextrico_{task_id}{source.suffix.lower()}"
        shutil.copy2(source, output / "train" / "images" / image_name)
        (output / "train" / "labels" / f"pseudo_contextrico_{task_id}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        image_count += 1

    data = yaml.safe_load((BASE_DATASET / "data.yaml").read_text(encoding="utf-8"))
    data["path"] = str(output)
    (output / "data.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    summary = {
        "new_training_images": image_count, "new_boxes_by_category": dict(box_counts),
        "pseudo_label_source": "calibrated source-constrained OCR + dark-pattern-yolo-v1",
        "validation_split": "copied unchanged from visual_dataset",
        "test_split": "copied unchanged from visual_dataset",
    }
    (output / "pseudo_label_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
