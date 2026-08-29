from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


FlowMode = Literal["controlled", "evidence_only"]
FlowPhase = Literal["acquisition", "exit", "cleanup"]
FlowActionType = Literal["goto", "click", "fill", "select", "check", "wait_for", "assert_text"]


class FlowActionSpec(BaseModel):
    action: FlowActionType
    selector: str | None = Field(default=None, max_length=1000)
    value: str | None = Field(default=None, max_length=2000)
    description: str = Field(min_length=1, max_length=300)
    commit: bool = False
    timeout_ms: int = Field(default=15_000, ge=500, le=60_000)

    @model_validator(mode="after")
    def validate_action_fields(self) -> "FlowActionSpec":
        if self.action == "goto" and not self.value:
            raise ValueError("goto actions require value")
        if self.action in {"click", "fill", "select", "check", "wait_for"} and not self.selector:
            raise ValueError(f"{self.action} actions require selector")
        if self.action in {"fill", "select"} and self.value is None:
            raise ValueError(f"{self.action} actions require value")
        if self.action == "assert_text" and not self.value:
            raise ValueError("assert_text actions require value")
        return self


class FlowDefinitionSpec(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=200)
    start_url: str | None = Field(default=None, max_length=2000)
    actions: list[FlowActionSpec] = Field(min_length=1, max_length=60)


class FlowPairRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    source: Literal["custom", "automation_exercise", "local_benchmark"] = "custom"
    mode: FlowMode = "evidence_only"
    acquisition: FlowDefinitionSpec
    exit: FlowDefinitionSpec
    cleanup_actions: list[FlowActionSpec] = Field(default_factory=list, max_length=20)
    allowed_origins: list[str] = Field(default_factory=list, max_length=10)
    analyse_models: bool = True

    @field_validator("allowed_origins")
    @classmethod
    def validate_origins(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            cleaned = value.rstrip("/")
            if not cleaned.startswith(("http://", "https://")):
                raise ValueError("allowed_origins must use http or https")
            normalized.append(cleaned)
        return list(dict.fromkeys(normalized))


class TargetPresentation(BaseModel):
    visible: bool = False
    viewport_area_ratio: float = Field(default=0, ge=0)
    opacity: float = Field(default=1, ge=0, le=1)
    font_size_px: float = Field(default=0, ge=0)
    contrast_ratio: float | None = Field(default=None, ge=0)


class FlowStepEvidence(BaseModel):
    obstruction_tags: list[str] = Field(default_factory=list)
    justified_tags: list[str] = Field(default_factory=list)
    bert_categories: list[str] = Field(default_factory=list)
    visual_cues: list[str] = Field(default_factory=list)
    text_excerpt: str = ""
    target_presentation: TargetPresentation | None = None


class FlowStepResult(BaseModel):
    index: int = Field(ge=0)
    phase: FlowPhase
    action: FlowActionType
    description: str
    status: Literal["completed", "blocked_at_commit", "failed"]
    url_before: str
    url_after: str
    duration_ms: int = Field(ge=0)
    page_transition: bool
    screenshot_path: str | None = None
    evidence: FlowStepEvidence = Field(default_factory=FlowStepEvidence)
    error: str | None = None


class FlowMetrics(BaseModel):
    meaningful_actions: int = Field(ge=0)
    clicks: int = Field(ge=0)
    form_fields: int = Field(ge=0)
    page_transitions: int = Field(ge=0)
    active_time_ms: int = Field(ge=0)
    obstruction_weight: float = Field(ge=0)
    justified_weight: float = Field(ge=0)
    effort_score: float = Field(ge=0)
    completed: bool


class FlowRunResult(BaseModel):
    name: str
    goal: str
    status: Literal["completed", "blocked_at_commit", "failed"]
    steps: list[FlowStepResult]
    metrics: FlowMetrics


class FlowFinding(BaseModel):
    category: Literal["obstruction_asymmetry"] = "obstruction_asymmetry"
    severity: Literal["none", "low", "medium", "high"]
    score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    candidate: bool
    effort_difference: float
    effort_ratio: float = Field(ge=0)
    evidence: list[str] = Field(default_factory=list)
    rationale: str
    calibration_version: str
    review_status: Literal["needs_review", "confirmed", "rejected"] = "needs_review"


class FlowPairResult(BaseModel):
    run_id: str
    name: str
    source: str
    mode: FlowMode
    acquisition: FlowRunResult
    exit: FlowRunResult
    finding: FlowFinding
    warnings: list[str] = Field(default_factory=list)


class FlowJob(BaseModel):
    run_id: str
    status: Literal["queued", "running", "completed", "failed"]
    request: FlowPairRequest
    created_at: datetime
    updated_at: datetime
    result: FlowPairResult | None = None
    error: str | None = None


class FlowDefinitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    request: FlowPairRequest


class FlowDefinitionResponse(FlowDefinitionCreate):
    id: str
    owner_id: str
    created_at: datetime
    updated_at: datetime


class FlowReviewRequest(BaseModel):
    decision: Literal["confirmed", "rejected", "needs_review"]
    severity: Literal["none", "low", "medium", "high"]
    notes: str = Field(default="", max_length=4000)


class FlowReviewResponse(FlowReviewRequest):
    id: str
    run_id: str
    reviewer_id: str
    created_at: datetime
    updated_at: datetime


class FlowDiscoveryCandidate(BaseModel):
    intent: Literal["acquisition", "exit"]
    text: str
    selector: str
    href: str | None = None
    confidence: float = Field(ge=0, le=1)


class FlowDiscoveryResponse(BaseModel):
    url: str
    candidates: list[FlowDiscoveryCandidate]
    note: str
