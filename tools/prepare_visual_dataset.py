"""Prepare a Roboflow YOLO export for local dark-pattern cue detection.

Roboflow's `NO DP` class describes a negative screenshot, not a visual object.
This tool removes its bounding boxes and keeps those images as background
examples. It also writes a project-local data.yaml containing the ten actual
visual-cue classes.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NO_DP_CLASS_ID = 10
CLASS_NAMES = [
    "ACTIVITY MESSAGE",
    "ATTENTION DISTRACTION",
    "COUNTDOWN TIMER",
    "DEFAULT CHOICE",
    "DISGUISED ADS",
    "GAMIFICATION",
    "HIGH DEMAND MESSAGE",
    "LIMITED TIME MESSAGE",
    "LOW STOCK MESSAGE",
    "NAGGING",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Extracted Roboflow YOLO dataset directory.")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "visual_dataset")
    args = parser.parse_args()

    source = args.source.resolve()
    output = args.output.resolve()
    if not (source / "data.yaml").exists():
        raise SystemExit(f"No data.yaml found in {source}")
    if output.exists():
        raise SystemExit(f"Output directory already exists: {output}. Remove it only if you intend to regenerate it.")

    for split in ("train", "valid", "test"):
        image_source = source / split / "images"
        label_source = source / split / "labels"
        image_output = output / split / "images"
        label_output = output / split / "labels"
        image_output.mkdir(parents=True)
        label_output.mkdir(parents=True)
        for image in image_source.iterdir():
            if image.is_file():
                shutil.copy2(image, image_output / image.name)
        for label in label_source.glob("*.txt"):
            positive_lines = []
            for line in label.read_text(encoding="utf-8").splitlines():
                values = line.split()
                if not values or int(values[0]) == NO_DP_CLASS_ID:
                    continue
                positive_lines.append(line)
            if positive_lines:
                (label_output / label.name).write_text("\n".join(positive_lines) + "\n", encoding="utf-8")

    data = {
        "path": str(output),
        "train": "train/images",
        "val": "valid/images",
        "test": "test/images",
        "names": {index: name for index, name in enumerate(CLASS_NAMES)},
    }
    (output / "data.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    print(f"Prepared visual dataset at {output}")


if __name__ == "__main__":
    main()
