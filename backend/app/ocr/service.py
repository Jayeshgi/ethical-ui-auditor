from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import os
import shutil

import cv2
import pytesseract
from PIL import Image
from pytesseract import Output


class OCRUnavailableError(RuntimeError):
    """Raised when the native Tesseract installation is unavailable."""


def _configure_tesseract() -> None:
    configured = os.getenv("TESSERACT_CMD")
    windows_default = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    executable = configured or shutil.which("tesseract") or (str(windows_default) if windows_default.exists() else None)
    if not executable:
        raise OCRUnavailableError("Tesseract is not installed or TESSERACT_CMD is not configured.")
    pytesseract.pytesseract.tesseract_cmd = executable


def extract_text_blocks(image_path: Path, minimum_confidence: float = 35.0) -> list[dict]:
    """Extract line-level OCR records with screenshot coordinates."""
    _configure_tesseract()
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"Unable to read screenshot: {image_path}")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    enlarged = cv2.resize(gray, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    prepared = cv2.threshold(enlarged, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    data = pytesseract.image_to_data(Image.fromarray(prepared), output_type=Output.DICT, config="--oem 1 --psm 11")

    lines: dict[tuple[int, int, int], list[tuple[str, float, int, int, int, int]]] = defaultdict(list)
    for index, raw_text in enumerate(data["text"]):
        text = raw_text.strip()
        try:
            confidence = float(data["conf"][index])
        except (TypeError, ValueError):
            continue
        if not text or confidence < minimum_confidence:
            continue
        key = (int(data["block_num"][index]), int(data["par_num"][index]), int(data["line_num"][index]))
        lines[key].append(
            (
                text,
                confidence,
                int(data["left"][index]) / 1.5,
                int(data["top"][index]) / 1.5,
                int(data["width"][index]) / 1.5,
                int(data["height"][index]) / 1.5,
            )
        )

    blocks: list[dict] = []
    for words in lines.values():
        x_values = [word[2] for word in words]
        y_values = [word[3] for word in words]
        right_values = [word[2] + word[4] for word in words]
        bottom_values = [word[3] + word[5] for word in words]
        blocks.append(
            {
                "text": " ".join(word[0] for word in words),
                "ocr_confidence": round(sum(word[1] for word in words) / len(words), 2),
                "bounding_box": {
                    "x": round(min(x_values), 2),
                    "y": round(min(y_values), 2),
                    "width": round(max(right_values) - min(x_values), 2),
                    "height": round(max(bottom_values) - min(y_values), 2),
                },
            }
        )
    return blocks

