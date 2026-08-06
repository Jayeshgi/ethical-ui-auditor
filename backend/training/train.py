from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import f1_score, precision_recall_fscore_support
from sklearn.model_selection import StratifiedGroupKFold
from torch.nn import BCEWithLogitsLoss
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from app.core.config import PROJECT_ROOT
from app.text_analysis.labels import DARK_PATTERN_LABELS
from training.data import DatasetRow, load_dataset, review_eligible


DEFAULT_DATASET = PROJECT_ROOT / "dataset_output" / "darkpatterndataset_augmented.csv"
DEFAULT_ARTIFACT_DIR = PROJECT_ROOT / "model_artifacts" / "dark_pattern_bert_v1"
BASE_MODEL = "bert-base-uncased"


class TextDataset(Dataset):
    def __init__(self, rows: list[DatasetRow], tokenizer) -> None:
        self.rows = rows
        self.tokenizer = tokenizer

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        row = self.rows[index]
        encoded = self.tokenizer(row.text, truncation=True, max_length=256, padding="max_length", return_tensors="pt")
        return {**{key: value.squeeze(0) for key, value in encoded.items()}, "labels": torch.tensor(row.labels, dtype=torch.float32)}


def _split_real_records(rows: list[DatasetRow]) -> tuple[list[DatasetRow], list[DatasetRow], list[DatasetRow]]:
    categories = np.array([row.category for row in rows])
    groups = np.array([row.page_id for row in rows])
    indices = np.arange(len(rows))
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
    train_val_idx, test_idx = next(splitter.split(indices, categories, groups))
    train_val = [rows[index] for index in train_val_idx]
    test = [rows[index] for index in test_idx]
    inner_categories = np.array([row.category for row in train_val])
    inner_groups = np.array([row.page_id for row in train_val])
    inner_indices = np.arange(len(train_val))
    inner_splitter = StratifiedGroupKFold(n_splits=4, shuffle=True, random_state=43)
    train_idx, validation_idx = next(inner_splitter.split(inner_indices, inner_categories, inner_groups))
    return [train_val[index] for index in train_idx], [train_val[index] for index in validation_idx], test


def _assert_evaluation_coverage(rows: list[DatasetRow], name: str) -> None:
    counts = Counter(row.category for row in rows)
    missing = [label for label in DARK_PATTERN_LABELS if counts[label] == 0]
    if missing:
        raise ValueError(f"{name} split has no real examples for: {', '.join(missing)}. Review and collect more real examples before training.")


def _evaluate(model, loader, device: torch.device) -> tuple[np.ndarray, np.ndarray]:
    model.eval()
    all_logits: list[np.ndarray] = []
    all_labels: list[np.ndarray] = []
    with torch.inference_mode():
        for batch in loader:
            labels = batch.pop("labels").numpy()
            logits = model(**{key: value.to(device) for key, value in batch.items()}).logits.cpu().numpy()
            all_logits.append(logits)
            all_labels.append(labels)
    return np.vstack(all_logits), np.vstack(all_labels)


def _calibrate_thresholds(logits: np.ndarray, labels: np.ndarray) -> dict[str, float]:
    probabilities = 1 / (1 + np.exp(-logits))
    thresholds: dict[str, float] = {}
    for index, label in enumerate(DARK_PATTERN_LABELS):
        truth = labels[:, index]
        if truth.sum() == 0:
            raise ValueError(f"Validation set has no positive real {label} examples.")
        candidates = np.arange(0.20, 0.86, 0.02)
        threshold = max(candidates, key=lambda value: f1_score(truth, probabilities[:, index] >= value, zero_division=0))
        thresholds[label] = round(float(threshold), 2)
    return thresholds


def _metrics(logits: np.ndarray, labels: np.ndarray, thresholds: dict[str, float]) -> dict:
    probabilities = 1 / (1 + np.exp(-logits))
    predictions = np.column_stack([probabilities[:, i] >= thresholds[label] for i, label in enumerate(DARK_PATTERN_LABELS)])
    precision, recall, f1, support = precision_recall_fscore_support(labels, predictions, average=None, zero_division=0)
    return {
        "macro_f1": round(float(f1_score(labels, predictions, average="macro", zero_division=0)), 4),
        "per_category": {
            label: {"precision": round(float(precision[i]), 4), "recall": round(float(recall[i]), 4), "f1": round(float(f1[i]), 4), "support": int(support[i])}
            for i, label in enumerate(DARK_PATTERN_LABELS)
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the permanent multi-label BERT text classifier.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument(
        "--allow-synthetic-evaluation",
        action="store_true",
        help="Permit synthetic rows in validation and test splits. Artifacts are marked research-only.",
    )
    args = parser.parse_args()

    random.seed(42)
    np.random.seed(42)
    torch.manual_seed(42)
    all_rows = load_dataset(args.dataset)
    if args.allow_synthetic_evaluation:
        train_rows, validation_rows, test_rows = _split_real_records(all_rows)
        evaluation_provenance = "synthetic_and_real"
        release_status = "research_only"
    else:
        real_rows = review_eligible(all_rows)
        real_train, validation_rows, test_rows = _split_real_records(real_rows)
        train_rows = real_train + [row for row in all_rows if row.source == "synthetic"]
        evaluation_provenance = "real_only"
        release_status = "eligible_for_review"
    _assert_evaluation_coverage(validation_rows, "Validation")
    _assert_evaluation_coverage(test_rows, "Test")

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(
        BASE_MODEL,
        num_labels=len(DARK_PATTERN_LABELS),
        problem_type="multi_label_classification",
        id2label=dict(enumerate(DARK_PATTERN_LABELS)),
        label2id={label: index for index, label in enumerate(DARK_PATTERN_LABELS)},
    )
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    train_loader = DataLoader(TextDataset(train_rows, tokenizer), batch_size=args.batch_size, shuffle=True)
    validation_loader = DataLoader(TextDataset(validation_rows, tokenizer), batch_size=args.batch_size)
    test_loader = DataLoader(TextDataset(test_rows, tokenizer), batch_size=args.batch_size)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    loss_fn = BCEWithLogitsLoss()

    for epoch in range(args.epochs):
        model.train()
        losses: list[float] = []
        for batch in train_loader:
            labels = batch.pop("labels").to(device)
            outputs = model(**{key: value.to(device) for key, value in batch.items()})
            loss = loss_fn(outputs.logits, labels)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            losses.append(float(loss.item()))
        print(f"epoch={epoch + 1} mean_loss={sum(losses) / len(losses):.4f}")

    validation_logits, validation_labels = _evaluate(model, validation_loader, device)
    thresholds = _calibrate_thresholds(validation_logits, validation_labels)
    test_logits, test_labels = _evaluate(model, test_loader, device)
    metrics = _metrics(test_logits, test_labels, thresholds)

    args.output.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.output)
    tokenizer.save_pretrained(args.output)
    (args.output / "thresholds.json").write_text(json.dumps(thresholds, indent=2), encoding="utf-8")
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (args.output / "metadata.json").write_text(
        json.dumps(
            {
                "model_version": "dark-pattern-bert-v1",
                "base_model": BASE_MODEL,
                "labels": list(DARK_PATTERN_LABELS),
                "dataset": str(args.dataset),
                "training_rows": len(train_rows),
                "validation_rows": len(validation_rows),
                "test_rows": len(test_rows),
                "synthetic_rows_train_only": sum(row.source == "synthetic" for row in train_rows),
                "evaluation_provenance": evaluation_provenance,
                "release_status": release_status,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"thresholds": thresholds, "test_metrics": metrics}, indent=2))


if __name__ == "__main__":
    main()
