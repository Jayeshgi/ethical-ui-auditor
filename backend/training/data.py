from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from app.text_analysis.labels import DARK_PATTERN_LABELS, NEUTRAL_LABEL


@dataclass(frozen=True)
class DatasetRow:
    record_id: str
    text: str
    labels: tuple[float, ...]
    category: str
    source: str
    page_id: str


def load_dataset(path: Path) -> list[DatasetRow]:
    rows: list[DatasetRow] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            category = raw["Pattern Category"].strip()
            if category not in {*DARK_PATTERN_LABELS, NEUTRAL_LABEL}:
                raise ValueError(f"Unexpected category {category!r} in {raw.get('record_id')!r}.")
            labels = tuple(float(category == label) for label in DARK_PATTERN_LABELS)
            rows.append(
                DatasetRow(
                    record_id=raw["record_id"],
                    text=raw["text"].strip(),
                    labels=labels,
                    category=category,
                    source=raw["source"],
                    page_id=raw["page_id"].strip() or raw["record_id"],
                )
            )
    if not rows or any(not row.text for row in rows):
        raise ValueError("Dataset must contain non-empty text records.")
    return rows


def review_eligible(rows: list[DatasetRow]) -> list[DatasetRow]:
    """Synthetic data can train the model but cannot validate or test it."""
    return [row for row in rows if row.source == "original"]

