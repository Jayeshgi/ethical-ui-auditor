"""Generate conservative Label Studio box proposals from OCR-visible dark-pattern text.

These are *machine proposals*, not ground truth.  They cover only categories
whose cue can be verified in text and must be reviewed before YOLO training.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from app.ocr.service import extract_text_blocks


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "annotation_queue" / "contextrico" / "manifest.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "annotation_queue" / "contextrico" / "tasks_with_machine_proposals.json"
RULES = {
    "ACTIVITY MESSAGE": re.compile(r"\b(?:recently\s+)?(?:bought|purchased|ordered|just sold)\b", re.I),
    "COUNTDOWN TIMER": re.compile(r"\b(?:\d{1,2}:){1,2}\d{2}\b|\btime remaining\b", re.I),
    "HIGH DEMAND MESSAGE": re.compile(r"\b(?:\d+|many)\s+(?:people|customers|shoppers|users)\b.*\b(?:viewing|looking|watching)\b|\bhigh demand\b", re.I),
    "LIMITED TIME MESSAGE": re.compile(r"\blimited time\b|\bhurry\b|\b(?:sale|offer|deal) ends?\b|\blast chance\b|\btoday only\b", re.I),
    "LOW STOCK MESSAGE": re.compile(r"\blow stock\b|\bonly\s+\d+\s+(?:left|remaining)\b|\b\d+\s+(?:left|remaining)\b", re.I),
}


def proposal_for(row: dict) -> tuple[dict, int]:
    labels = row["suggested_labels"].split("|")
    applicable = {label: RULES[label] for label in labels if label in RULES}
    task = {
        "id": row["task_id"],
        "data": {
            "image": f"/data/local-files/?d={row['image_path']}",
            "source_labels": ", ".join(labels),
            "task_id": row["task_id"],
            "split": row["split"],
        },
    }
    if not applicable:
        return task, 0
    path = PROJECT_ROOT / row["image_path"]
    blocks = extract_text_blocks(path)
    width, height = Image.open(path).size
    results = []
    for block in blocks:
        text = block["text"]
        for label, expression in applicable.items():
            if not expression.search(text):
                continue
            box = block["bounding_box"]
            results.append({
                "from_name": "label", "to_name": "image", "type": "rectanglelabels",
                "original_width": width, "original_height": height, "image_rotation": 0,
                "value": {
                    "x": round(box["x"] / width * 100, 3), "y": round(box["y"] / height * 100, 3),
                    "width": round(box["width"] / width * 100, 3), "height": round(box["height"] / height * 100, 3),
                    "rotation": 0, "rectanglelabels": [label],
                },
            })
    if results:
        task["predictions"] = [{"model_version": "ocr-rule-proposals-v1", "score": 0.6, "result": results}]
    return task, len(results)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    with args.manifest.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        generated = list(pool.map(proposal_for, rows))
    tasks, proposal_count = zip(*generated)
    args.output.write_text(json.dumps(list(tasks), indent=2), encoding="utf-8")
    print(f"Wrote {sum(proposal_count)} proposals for {sum(count > 0 for count in proposal_count)} tasks to {args.output}")


if __name__ == "__main__":
    main()
