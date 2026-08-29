"""Train the project-local YOLO visual-cue detector."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = PROJECT_ROOT / "data" / "visual_dataset" / "data.yaml"
DEFAULT_OUTPUT = PROJECT_ROOT / "model_artifacts" / "dark_pattern_yolo_v1"
BASELINE_METADATA = PROJECT_ROOT / "model_artifacts" / "dark_pattern_yolo_v1" / "metadata.json"
YOLO_CONFIG_ROOT = PROJECT_ROOT / "runtime_data" / "ultralytics"
MATPLOTLIB_CONFIG_ROOT = PROJECT_ROOT / "runtime_data" / "matplotlib"
(YOLO_CONFIG_ROOT / "Ultralytics").mkdir(parents=True, exist_ok=True)
MATPLOTLIB_CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("YOLO_CONFIG_DIR", str(YOLO_CONFIG_ROOT))
os.environ.setdefault("MPLCONFIGDIR", str(MATPLOTLIB_CONFIG_ROOT))

from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=-1, help="-1 lets Ultralytics choose a GPU-safe batch size.")
    parser.add_argument("--model", default="yolo26n.pt")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model-version", default="dark-pattern-yolo-v1")
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--device", default="0")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    if not args.data.exists():
        raise SystemExit(f"Prepared data.yaml not found: {args.data}")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    model = YOLO(args.model)
    results = model.train(
        data=str(args.data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        project=str(output),
        name="training_run",
        exist_ok=True,
        pretrained=True,
        seed=42,
        patience=args.patience,
        device=args.device,
        workers=args.workers,
    )
    best = output / "training_run" / "weights" / "best.pt"
    deployable_weights = output / "best.pt"
    shutil.copy2(best, deployable_weights)
    results_csv = output / "training_run" / "results.csv"
    epochs_completed = max(0, len(results_csv.read_text(encoding="utf-8").splitlines()) - 1)
    best_model = YOLO(str(best))
    metrics = best_model.val(data=str(args.data), split="test", device=args.device)
    baseline = json.loads(BASELINE_METADATA.read_text(encoding="utf-8")) if BASELINE_METADATA.exists() else None
    pseudo_summary_path = args.data.parent / "pseudo_label_summary.json"
    pseudo_summary = json.loads(pseudo_summary_path.read_text(encoding="utf-8")) if pseudo_summary_path.exists() else None
    map_50_95 = float(metrics.box.map)
    metadata = {
        "model_version": args.model_version,
        "base_model": args.model,
        "weights": str(deployable_weights),
        "dataset": str(args.data),
        "epochs_requested": args.epochs,
        "epochs_completed": epochs_completed,
        "image_size": args.imgsz,
        "test_map50_95": map_50_95,
        "test_map50": float(metrics.box.map50),
        "test_precision": float(metrics.box.mp),
        "test_recall": float(metrics.box.mr),
        "release_status": "research_only",
        "limitation": "Small, imbalanced visual dataset; validate on reviewed real webpages before compliance use.",
        "baseline": baseline,
        "pseudo_label_summary": pseudo_summary,
        "improved_over_v1_map50_95": bool(baseline and map_50_95 > float(baseline["test_map50_95"])),
    }
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Best weights: {best}")
    print(f"Metadata: {output / 'metadata.json'}")


if __name__ == "__main__":
    main()
