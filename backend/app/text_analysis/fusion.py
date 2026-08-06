from __future__ import annotations

import re
from collections.abc import Iterable

from rapidfuzz.fuzz import ratio


def _normalise(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _normalise(value).lower()).strip()


def fuse_text_blocks(dom_blocks: Iterable[dict], ocr_blocks: Iterable[dict]) -> list[dict]:
    """Merge matching DOM/OCR text while preferring accurate DOM text."""
    merged: list[dict] = []
    for block in dom_blocks:
        text = _normalise(str(block.get("text", "")))
        if text:
            merged.append({**block, "text": text, "source": "dom", "ocr_confidence": None})

    for candidate in ocr_blocks:
        text = _normalise(str(candidate.get("text", "")))
        if not text:
            continue
        candidate_key = _key(text)
        matching = next(
            (
                item
                for item in merged
                if candidate_key == _key(item["text"])
                or ratio(candidate_key, _key(item["text"])) >= 92
            ),
            None,
        )
        if matching:
            matching["source"] = "both"
            matching["ocr_confidence"] = candidate.get("ocr_confidence")
            if not matching.get("bounding_box"):
                matching["bounding_box"] = candidate.get("bounding_box")
        else:
            merged.append({**candidate, "text": text, "source": "ocr", "selector": None})
    return merged

