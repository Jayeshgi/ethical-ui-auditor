"""Create Label Studio tasks for reviewing ContextRico-DP screenshots.

The ContextRico-DP release provides screenshot-level dark-pattern labels, not
locations.  This script turns only taxonomy-compatible screenshots into manual
bounding-box tasks.  Its suggested labels are hints for the reviewer and are
never converted into YOLO boxes automatically.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "data" / "external_sources" / "contextrico" / "extracted" / "ContextRico-DP"
GROUND_TRUTH = PROJECT_ROOT / "data" / "external_sources" / "contextrico" / "groundtruth.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "annotation_queue" / "contextrico"

LABEL_MAP = {
    "Activity Message": "ACTIVITY MESSAGE",
    "Attention Distraction": "ATTENTION DISTRACTION",
    "Countdown Timer": "COUNTDOWN TIMER",
    "Default Choice": "DEFAULT CHOICE",
    "Disguised Ad": "DISGUISED ADS",
    "Gamification": "GAMIFICATION",
    "High Demand Message": "HIGH DEMAND MESSAGE",
    "Limited Time Message": "LIMITED TIME MESSAGE",
    "Low Stock Message": "LOW STOCK MESSAGE",
    "Nagging": "NAGGING",
}

LABEL_CONFIG = """<View>
  <View style=\"display:flex;gap:24px\">
    <View style=\"width:70%\"><Image name=\"image\" value=\"$image\" zoom=\"true\"/></View>
    <View style=\"width:30%\">
      <Header value=\"Source-label hint (verify visually)\"/>
      <Text name=\"source_labels\" value=\"$source_labels\"/>
      <Header value=\"Draw a tight box around each visible cue\"/>
      <RectangleLabels name=\"label\" toName=\"image\">
        <Label value=\"ACTIVITY MESSAGE\" background=\"#1f77b4\"/>
        <Label value=\"ATTENTION DISTRACTION\" background=\"#ff7f0e\"/>
        <Label value=\"COUNTDOWN TIMER\" background=\"#2ca02c\"/>
        <Label value=\"DEFAULT CHOICE\" background=\"#d62728\"/>
        <Label value=\"DISGUISED ADS\" background=\"#9467bd\"/>
        <Label value=\"GAMIFICATION\" background=\"#8c564b\"/>
        <Label value=\"HIGH DEMAND MESSAGE\" background=\"#e377c2\"/>
        <Label value=\"LIMITED TIME MESSAGE\" background=\"#7f7f7f\"/>
        <Label value=\"LOW STOCK MESSAGE\" background=\"#bcbd22\"/>
        <Label value=\"NAGGING\" background=\"#17becf\"/>
      </RectangleLabels>
      <Choices name=\"review_status\" toName=\"image\" choice=\"single\" showInline=\"true\">
        <Choice value=\"annotated\"/><Choice value=\"no_compatible_cue\"/>
      </Choices>
    </View>
  </View>
</View>
"""


def task_split(relative_path: str) -> str:
    """Deterministic 85/15 train/validation split; the original test split stays untouched."""
    return "valid" if int(hashlib.sha256(relative_path.encode()).hexdigest(), 16) % 100 < 15 else "train"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--ground-truth", type=Path, default=GROUND_TRUTH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    output = args.output.resolve()
    labels_by_name = json.loads(args.ground_truth.read_text(encoding="utf-8"))
    candidates: dict[str, Path] = {}
    for image in source_root.rglob("*"):
        if image.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            candidates.setdefault(image.name, image)

    tasks = []
    manifest_rows = []
    for filename, record in sorted(labels_by_name.items()):
        image = candidates.get(filename)
        mapped = sorted({LABEL_MAP[label] for label in record["labels"] if label in LABEL_MAP})
        if image is None or not mapped:
            continue
        relative = image.relative_to(PROJECT_ROOT).as_posix()
        task_id = hashlib.sha256(relative.encode()).hexdigest()[:16]
        split = task_split(relative)
        tasks.append({
            "id": task_id,
            "data": {
                "image": f"/data/local-files/?d={relative}",
                "source_labels": ", ".join(mapped),
                "task_id": task_id,
                "split": split,
            },
        })
        manifest_rows.append({
            "task_id": task_id,
            "image_path": relative,
            "suggested_labels": "|".join(mapped),
            "split": split,
            "status": "pending",
        })

    output.mkdir(parents=True, exist_ok=True)
    (output / "label_config.xml").write_text(LABEL_CONFIG, encoding="utf-8")
    (output / "tasks.json").write_text(json.dumps(tasks, indent=2), encoding="utf-8")
    with (output / "manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest_rows[0]))
        writer.writeheader()
        writer.writerows(manifest_rows)
    print(f"Created {len(tasks)} review tasks in {output}")


if __name__ == "__main__":
    main()
