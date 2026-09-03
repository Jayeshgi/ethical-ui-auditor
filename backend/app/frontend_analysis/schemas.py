from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


BehaviorCategory = Literal[
    "resetting_countdown",
    "non_expiring_offer",
    "session_relative_deadline",
    "fabricated_scarcity",
    "fabricated_social_proof",
    "preselected_option",
    "hidden_rejection",
    "silent_cart_addition",
    "late_price_disclosure",
    "repeated_nagging",
    "misleading_action",
    "subscription_disclosure",
]
BehaviorStatus = Literal["detected", "suspicious", "inconclusive", "not_detected"]


class BehaviorTimelineSample(BaseModel):
    elapsed_ms: int = Field(ge=0)
    value: str = Field(max_length=500)
    parsed_seconds: int | None = Field(default=None, ge=0)
    event: str = Field(default="observation", max_length=80)


class BehaviorDOMSnapshot(BaseModel):
    elapsed_ms: int = Field(ge=0)
    phase: Literal["initial", "observed", "reload", "clean_session"]
    timers: list[dict] = Field(default_factory=list)
    claims: list[dict] = Field(default_factory=list)
    choices: list[dict] = Field(default_factory=list)
    dialogs: list[str] = Field(default_factory=list)


class CodeEvidence(BaseModel):
    source: Literal["inline_script", "script_asset", "rendered_dom", "computed_style"]
    asset_url: str | None = Field(default=None, max_length=2000)
    sha256: str | None = Field(default=None, min_length=64, max_length=64)
    excerpt: str = Field(max_length=600)
    signals: list[str] = Field(default_factory=list)


class NetworkObservation(BaseModel):
    method: str = Field(max_length=16)
    url: str = Field(max_length=2000)
    status: int | None = Field(default=None, ge=0, le=599)
    resource_type: str = Field(default="other", max_length=40)
    content_type: str | None = Field(default=None, max_length=160)
    response_sha256: str | None = Field(default=None, min_length=64, max_length=64)


class FrontendArtifactSummary(BaseModel):
    original_html_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    rendered_dom_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    inline_script_count: int = Field(default=0, ge=0)
    script_asset_count: int = Field(default=0, ge=0)
    script_asset_hashes: dict[str, str] = Field(default_factory=dict)
    stylesheet_asset_hashes: dict[str, str] = Field(default_factory=dict)
    storage_keys: list[str] = Field(default_factory=list)
    cookie_names: list[str] = Field(default_factory=list)
    network_observations: list[NetworkObservation] = Field(default_factory=list)
    code_evidence: list[CodeEvidence] = Field(default_factory=list)


class FrontendBehaviorFinding(BaseModel):
    finding_id: str | None = None
    page_url: str | None = Field(default=None, max_length=2000)
    category: BehaviorCategory
    dark_pattern_category: str
    status: BehaviorStatus
    severity: Literal["none", "low", "medium", "high"]
    score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    element: str | None = Field(default=None, max_length=1000)
    initial_value: str | None = Field(default=None, max_length=500)
    observed_value: str | None = Field(default=None, max_length=500)
    after_reload: str | None = Field(default=None, max_length=500)
    clean_session_value: str | None = Field(default=None, max_length=500)
    offer_changed_at_expiry: bool | None = None
    implementation_signal: str | None = Field(default=None, max_length=160)
    evidence: list[str] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)
    timeline: list[BehaviorTimelineSample] = Field(default_factory=list)
    code_evidence: list[CodeEvidence] = Field(default_factory=list)
    screenshot_paths: list[str] = Field(default_factory=list)
    bert_categories: list[str] = Field(default_factory=list)
    visual_cues: list[str] = Field(default_factory=list)
    rationale: str


class FrontendBehaviorReport(BaseModel):
    status: Literal["completed", "completed_with_warnings", "not_requested"] = "not_requested"
    observation_seconds: int = Field(default=0, ge=0, le=90)
    findings: list[FrontendBehaviorFinding] = Field(default_factory=list)
    dom_snapshots: list[BehaviorDOMSnapshot] = Field(default_factory=list)
    artifacts: FrontendArtifactSummary = Field(default_factory=FrontendArtifactSummary)
    screenshots: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    note: str = (
        "Runtime behaviour is primary evidence. Public JavaScript and markup clues are supporting evidence, "
        "not proof of a dark pattern."
    )
