from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, Field

from app.frontend_analysis.schemas import FrontendBehaviorReport


class ScanRequest(BaseModel):
    url: AnyHttpUrl
    max_pages: int = Field(default=3, ge=1, le=5)
    scroll_steps: int = Field(default=2, ge=0, le=5)
    analyse_behavior: bool = True
    behavior_observation_seconds: int = Field(default=30, ge=5, le=90)


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
    evidence_rules: list[str] = Field(default_factory=list)
    status: Literal["detected"] = "detected"
    source: Literal["dom", "ocr", "both"]
    bounding_box: BoundingBox | None = None
    selector: str | None = None


class VisualCue(BaseModel):
    cue: str
    model_confidence: float = Field(ge=0, le=1)
    threshold: float = Field(ge=0, le=1)
    model_version: str
    source: Literal["visual"] = "visual"
    bounding_box: BoundingBox
    supports_categories: list[str] = Field(default_factory=list)


class FusionLink(BaseModel):
    category: str
    text_finding_index: int = Field(ge=0)
    visual_cue_index: int = Field(ge=0)
    spatial_overlap: float = Field(ge=0, le=1)
    rationale: str


class PageResult(BaseModel):
    url: str
    title: str
    screenshot_path: str
    text_blocks: list[TextBlock]
    findings: list[Finding]
    visual_cues: list[VisualCue] = Field(default_factory=list)
    fusion_links: list[FusionLink] = Field(default_factory=list)
    frontend_behavior: FrontendBehaviorReport = Field(default_factory=FrontendBehaviorReport)


class ScanResponse(BaseModel):
    scan_id: str
    status: Literal["completed", "completed_with_warnings"]
    pages: list[PageResult]
    warnings: list[str] = Field(default_factory=list)


class ScanJob(BaseModel):
    scan_id: str
    status: Literal["queued", "running", "completed", "failed"]
    request: ScanRequest
    created_at: datetime
    updated_at: datetime
    result: ScanResponse | None = None
    error: str | None = None


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=10, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class UserPublic(BaseModel):
    id: str
    email: str
    role: Literal["reviewer", "admin"]
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime


class ReviewRequest(BaseModel):
    page_index: int = Field(ge=0)
    evidence_type: Literal["text", "visual"]
    evidence_index: int = Field(ge=0)
    decision: Literal["confirmed", "rejected", "needs_review"]
    severity: Literal["low", "medium", "high"] = "medium"
    notes: str = Field(default="", max_length=2000)


class ReviewResponse(ReviewRequest):
    id: str
    scan_id: str
    reviewer_id: str
    created_at: datetime
    updated_at: datetime


class ScanComparison(BaseModel):
    left_scan_id: str
    right_scan_id: str
    left_text_categories: dict[str, int]
    right_text_categories: dict[str, int]
    text_category_delta: dict[str, int]
    left_visual_cues: dict[str, int]
    right_visual_cues: dict[str, int]
    visual_cue_delta: dict[str, int]
