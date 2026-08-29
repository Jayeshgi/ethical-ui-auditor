from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path

from app.core.config import PROJECT_ROOT, VISUAL_CONFIDENCE_THRESHOLD, VISUAL_MODEL_PATH


class VisualModelUnavailableError(RuntimeError):
    """Raised when the visual model cannot be loaded."""


@dataclass(frozen=True)
class VisualPrediction:
    cue: str
    confidence: float
    bounding_box: dict[str, float]


class DarkPatternVisualDetector:
    """Lazy wrapper around the validated YOLO visual-cue checkpoint."""

    def __init__(self, model_path: Path = VISUAL_MODEL_PATH, confidence: float = VISUAL_CONFIDENCE_THRESHOLD) -> None:
        self.model_path = model_path.resolve()
        if not self.model_path.exists():
            raise VisualModelUnavailableError(f"Visual model weights are unavailable: {self.model_path}")
        if not 0 < confidence <= 1:
            raise VisualModelUnavailableError("Visual confidence threshold must be between 0 and 1.")
        self.confidence = confidence
        metadata_path = self.model_path.parent / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        self.version = str(metadata.get("model_version", self.model_path.parent.name))

        yolo_config = PROJECT_ROOT / "runtime_data" / "ultralytics"
        matplotlib_config = PROJECT_ROOT / "runtime_data" / "matplotlib"
        yolo_config.mkdir(parents=True, exist_ok=True)
        matplotlib_config.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("YOLO_CONFIG_DIR", str(yolo_config))
        os.environ.setdefault("MPLCONFIGDIR", str(matplotlib_config))

        try:
            import torch
            from ultralytics import YOLO

            self.device: int | str = 0 if torch.cuda.is_available() else "cpu"
            self._model = YOLO(str(self.model_path))
        except Exception as error:
            raise VisualModelUnavailableError(f"Could not load visual model: {type(error).__name__}: {error}") from error

    def predict(self, image_path: Path) -> list[VisualPrediction]:
        try:
            result = self._model.predict(
                source=str(image_path), conf=self.confidence, device=self.device, verbose=False
            )[0]
        except Exception as error:
            raise RuntimeError(f"Visual inference failed: {type(error).__name__}: {error}") from error

        predictions: list[VisualPrediction] = []
        if result.boxes is None:
            return predictions
        for box in result.boxes:
            x1, y1, x2, y2 = (float(value) for value in box.xyxy[0].tolist())
            class_id = int(box.cls[0])
            predictions.append(
                VisualPrediction(
                    cue=str(result.names[class_id]),
                    confidence=float(box.conf[0]),
                    bounding_box={"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1},
                )
            )
        return predictions
