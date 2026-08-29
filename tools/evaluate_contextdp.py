"""Evaluate the text BERT model on AidUI's web CONTEXTDP benchmark.

The script evaluates only annotations that have a clear semantic mapping to this
project's taxonomy.  It crops each annotated UI region, reads it with the same
OCR service used by the application, and classifies the resulting text with the
saved BERT artifact.  This is an external, OCR-mediated evaluation rather than
an evaluation of AidUI's visual detector.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image
from sklearn.metrics import classification_report, precision_recall_fscore_support


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.ocr.service import extract_text_blocks  # noqa: E402
from app.text_analysis.labels import DARK_PATTERN_LABELS  # noqa: E402
from app.text_analysis.model import DarkPatternBertClassifier  # noqa: E402


# AidUI labels that cannot be mapped without making an unsupported assumption
# (for example, visual attention distraction) are deliberately excluded.
AIDUI_TO_BERT = {
    "ACTIVITY MESSAGE": "social_proof",
    "COUNTDOWN TIMER": "false_urgency",
    "LIMITED TIME MESSAGE": "false_urgency",
    "LOW STOCK MESSAGE": "false_scarcity",
    "HIGH DEMAND MESSAGE": "false_scarcity",
    "DEFAULT CHOICE": "forced_consent",
}


def load_annotations(annotation_path: Path) -> tuple[dict[int, str], list[dict]]:
    data = json.loads(annotation_path.read_text(encoding="utf-8"))
    categories = {item["id"]: item["name"] for item in data["categories"]}
    images = {item["id"]: item["file_name"] for item in data["images"]}
    records = []
    for annotation in data["annotations"]:
        aidui_label = categories[annotation["category_id"]]
        if aidui_label not in AIDUI_TO_BERT:
            continue
        records.append(
            {
                "image": images[annotation["image_id"]],
                "aidui_label": aidui_label,
                "expected_label": AIDUI_TO_BERT[aidui_label],
                "bbox": annotation["bbox"],
            }
        )
    return categories, records


def crop_and_read(image_path: Path, bbox: list[float], work_dir: Path, sequence: int) -> str:
    x, y, width, height = bbox
    with Image.open(image_path) as image:
        left = max(0, int(x))
        top = max(0, int(y))
        right = min(image.width, int(x + width))
        bottom = min(image.height, int(y + height))
        if right <= left or bottom <= top:
            return ""
        crop_path = work_dir / f"crop_{sequence}.png"
        image.crop((left, top, right, bottom)).save(crop_path)
    return " ".join(block["text"] for block in extract_text_blocks(crop_path)).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=PROJECT_ROOT / ".aidui-review" / "evaluation" / "evaluation_dataset",
        help="Path containing web/result.json and web/images.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "runtime_data" / "contextdp_web_bert_evaluation.json",
    )
    args = parser.parse_args()

    web_root = args.dataset_root / "web"
    categories, records = load_annotations(web_root / "result.json")
    classifier = DarkPatternBertClassifier()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="contextdp-ocr-") as temporary:
        work_dir = Path(temporary)
        for index, record in enumerate(records):
            text = crop_and_read(web_root / record["image"], record["bbox"], work_dir, index)
            predictions = classifier.predict(text) if text else []
            predicted_labels = [prediction.category for prediction in predictions]
            results.append({**record, "ocr_text": text, "predicted_labels": predicted_labels})

    comparable_labels = sorted(set(AIDUI_TO_BERT.values()))
    y_true = [[int(row["expected_label"] == label) for label in comparable_labels] for row in results]
    y_pred = [[int(label in row["predicted_labels"]) for label in comparable_labels] for row in results]
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, average=None, zero_division=0
    )
    per_label = {
        label: {"precision": round(float(p), 4), "recall": round(float(r), 4), "f1": round(float(f), 4), "support": int(s)}
        for label, p, r, f, s in zip(comparable_labels, precision, recall, f1, support, strict=True)
    }
    payload = {
        "benchmark": "AidUI CONTEXTDP web",
        "method": "OCR each AidUI annotated bounding box, then classify the extracted text with dark-pattern-bert-v1.",
        "model_version": classifier.version,
        "total_web_annotations": sum(1 for _ in json.loads((web_root / "result.json").read_text(encoding="utf-8"))["annotations"]),
        "evaluated_annotations": len(results),
        "excluded_aidui_labels": sorted(set(categories.values()) - set(AIDUI_TO_BERT) - {"NO DP"}),
        "label_mapping": AIDUI_TO_BERT,
        "per_label_metrics": per_label,
        "classification_report": classification_report(y_true, y_pred, target_names=comparable_labels, zero_division=0, output_dict=True),
        "ocr_empty_crops": sum(not row["ocr_text"] for row in results),
        "prediction_counts": dict(Counter(label for row in results for label in row["predicted_labels"])),
        "records": results,
        "limitations": [
            "CONTEXTDP is a screenshot benchmark; this does not evaluate DOM-text extraction or live crawling.",
            "Only labels with a documented semantic mapping are scored.",
            "NO DP screenshots are excluded because this crop-level protocol evaluates annotated positive UI regions.",
        ],
    }
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")
    print(json.dumps(per_label, indent=2))


if __name__ == "__main__":
    main()
