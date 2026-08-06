from __future__ import annotations

from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, Field


class ScanRequest(BaseModel):
    url: AnyHttpUrl
    max_pages: int = Field(default=3, ge=1, le=5)
    scroll_steps: int = Field(default=2, ge=0, le=5)


class BoundingBox(BaseModel):
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(ge=0)
    height: float = Field(ge=0)


class TextBlock(BaseModel):
    text: str
    source: Literal["dom", "ocr", "both"]
    bounding_box: BoundingBox | None = None
    selector: str | None = None
    ocr_confidence: float | None = Field(default=None, ge=0, le=100)


class Finding(BaseModel):
    category: str
    model_confidence: float = Field(ge=0, le=1)
    threshold: float = Field(ge=0, le=1)
    model_version: str
    phrase: str
    evidence_rules: list[str] = []
    status: Literal["detected"] = "detected"
    source: Literal["dom", "ocr", "both"]
    bounding_box: BoundingBox | None = None
    selector: str | None = None


class PageResult(BaseModel):
    url: str
    title: str
    screenshot_path: str
    text_blocks: list[TextBlock]
    findings: list[Finding]


class ScanResponse(BaseModel):
    scan_id: str
    status: Literal["completed", "completed_with_warnings"]
    pages: list[PageResult]
    warnings: list[str] = []
