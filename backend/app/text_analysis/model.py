from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from app.core.config import PROJECT_ROOT
from app.text_analysis.labels import DARK_PATTERN_LABELS


MODEL_ARTIFACT_DIR = PROJECT_ROOT / "model_artifacts" / "dark_pattern_bert_v1"


class ModelUnavailableError(RuntimeError):
    """The service must not substitute heuristic results when the trained model is absent."""


@dataclass(frozen=True)
class ModelPrediction:
    category: str
    confidence: float
    threshold: float


class DarkPatternBertClassifier:
    def __init__(self, artifact_dir: Path = MODEL_ARTIFACT_DIR) -> None:
        metadata_path = artifact_dir / "metadata.json"
        thresholds_path = artifact_dir / "thresholds.json"
        if not metadata_path.exists() or not thresholds_path.exists():
            raise ModelUnavailableError(
                "No trained BERT artifact is available. Train and validate the model before starting scans."
            )
        self.metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.thresholds: dict[str, float] = json.loads(thresholds_path.read_text(encoding="utf-8"))
        if tuple(self.metadata.get("labels", [])) != DARK_PATTERN_LABELS:
            raise ModelUnavailableError("The trained model label mapping does not match the application taxonomy.")
        self.tokenizer = AutoTokenizer.from_pretrained(artifact_dir)
        self.model = AutoModelForSequenceClassification.from_pretrained(artifact_dir)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device)
        self.model.eval()

    @property
    def version(self) -> str:
        return str(self.metadata["model_version"])

    @property
    def validation_warning(self) -> str | None:
        provenance = self.metadata.get("evaluation_provenance")
        if provenance == "synthetic_and_real":
            return "Model thresholds were evaluated with synthetic and real examples; validate with real held-out data before compliance use."
        return None

    @torch.inference_mode()
    def predict(self, text: str) -> list[ModelPrediction]:
        encoded = {key: value.to(self.device) for key, value in self.tokenizer(text, return_tensors="pt", truncation=True, max_length=256).items()}
        probabilities = torch.sigmoid(self.model(**encoded).logits[0]).tolist()
        predictions = [
            ModelPrediction(label, float(probability), float(self.thresholds[label]))
            for label, probability in zip(DARK_PATTERN_LABELS, probabilities, strict=True)
            if probability >= self.thresholds[label]
        ]
        return sorted(predictions, key=lambda result: result.confidence, reverse=True)
