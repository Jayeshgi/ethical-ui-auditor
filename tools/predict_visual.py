"""Run the trained visual detector on one image and save reviewable evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
YOLO_CONFIG_ROOT = PROJECT_ROOT / "runtime_data" / "ultralytics"
MATPLOTLIB_CONFIG_ROOT = PROJECT_ROOT / "runtime_data" / "matplotlib"
(YOLO_CONFIG_ROOT / "Ultralytics").mkdir(parents=True, exist_ok=True)
MATPLOTLIB_CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("YOLO_CONFIG_DIR", str(YOLO_CONFIG_ROOT))
os.environ.setdefault("MPLCONFIGDIR", str(MATPLOTLIB_CONFIG_ROOT))

import cv2  # noqa: E402
import torch  # noqa: E402
from ultralytics import YOLO  # noqa: E402


DEFAULT_MODEL = PROJECT_ROOT / "model_artifacts" / "dark_pattern_yolo_v2" / "best.pt"
DEFAULT_OUTPUT = PROJECT_ROOT / "runtime_data" / "visual_predictions"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="JPEG or PNG screenshot to inspect.")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if not args.image.exists():
        raise SystemExit(f"Input image does not exist: {args.image}")
    if not args.model.exists():
        raise SystemExit(f"Trained model does not exist: {args.model}")
    if not 0.0 <= args.confidence <= 1.0:
        raise SystemExit("--confidence must be between 0 and 1")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    device = 0 if torch.cuda.is_available() else "cpu"
    result = YOLO(str(args.model)).predict(
        source=str(args.image), conf=args.confidence, device=device, verbose=False
    )[0]

    detections = []
    if result.boxes is not None:
        for box in result.boxes:
            x1, y1, x2, y2 = (float(value) for value in box.xyxy[0].tolist())
            class_id = int(box.cls[0])
            detections.append(
                {
                    "class_id": class_id,
                    "class_name": result.names[class_id],
                    "confidence": round(float(box.conf[0]), 4),
                    "bounding_box": {
                        "x": round(x1, 2),
                        "y": round(y1, 2),
                        "width": round(x2 - x1, 2),
                        "height": round(y2 - y1, 2),
                    },
                }
            )

    stem = args.image.stem
    json_path = args.output_dir / f"{stem}.json"
    annotated_path = args.output_dir / f"{stem}_annotated.jpg"
    payload = {
        "input_image": str(args.image.resolve()),
        "model": str(args.model.resolve()),
        "device": str(device),
        "confidence_threshold": args.confidence,
        "detection_count": len(detections),
        "detections": detections,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if not cv2.imwrite(str(annotated_path), result.plot()):
        raise SystemExit(f"Could not write annotated image: {annotated_path}")

    print(f"Device: {device}")
    print(f"Detections: {len(detections)}")
    for item in detections:
        print(f"- {item['class_name']}: {item['confidence']:.4f}")
    print(f"JSON: {json_path}")
    print(f"Annotated image: {annotated_path}")


if __name__ == "__main__":
    main()
