from __future__ import annotations

from datetime import datetime
import re
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import AnyHttpUrl, BaseModel, Field, SecretStr, field_validator, model_validator

from app.frontend_analysis.schemas import FrontendBehaviorReport
from app.flow_analysis.schemas import FlowMetrics, FlowMode, FlowStepResult, TargetPresentation
from app.schemas import Finding, FusionLink, VisualCue


_SENSITIVE_QUERY_KEY = re.compile(
    r"^(?:password|passwd|pwd|token|access_token|refresh_token|id_token|api_?key|"
    r"client_secret|secret|session|session_?id|authorization)$",
    re.IGNORECASE,
)


def _reject_embedded_url_secrets(value: AnyHttpUrl, field_name: str) -> AnyHttpUrl:
    """Keep credentials and bearer material out of persisted URL fields."""

    parsed = urlsplit(str(value))
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field_name} must not contain embedded user information")
    sensitive_keys = [
        key
        for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
        if _SENSITIVE_QUERY_KEY.match(key)
    ]
    if sensitive_keys:
        raise ValueError(f"{field_name} must not contain secret-bearing query parameters")
    return value


def _normalize_origin(value: str) -> str:
    parsed = urlsplit(value.strip())
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if scheme not in {"http", "https"} or not hostname:
        raise ValueError("allowed_origins must use a valid http or https origin")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("allowed_origins must not contain embedded user information")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("allowed_origins must contain only scheme, host, and optional port")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("allowed_origins contains an invalid port") from error
    host = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    return f"{scheme}://{host}"


GoalFamily = Literal[
    "account_create_delete",
    "subscribe_cancel",
    "newsletter_subscribe_unsubscribe",
    "consent_grant_withdraw",
    "notifications_enable_disable",
    "integration_connect_disconnect",
    "payment_method_add_remove",
    "loyalty_join_leave",
    "data_share_revoke",
    "purchase_return",
]
GoalFamilyRequest = Literal[
    "auto",
    "account_create_delete",
    "subscribe_cancel",
    "newsletter_subscribe_unsubscribe",
    "consent_grant_withdraw",
    "notifications_enable_disable",
    "integration_connect_disconnect",
    "payment_method_add_remove",
    "loyalty_join_leave",
    "data_share_revoke",
    "purchase_return",
]
MechanismCategory = Literal[
    "hidden_exit",
    "forced_reason",
    "retention_obstruction",
    "repeated_confirmation",
    "channel_switch",
    "forced_contact",
    "delayed_execution",
    "redirect_loop",
    "dead_end",
    "unnecessary_form_burden",
    "information_overload",
    "policy_interface_mismatch",
]
FindingCategory = Literal[
    "roach_motel",
    "hidden_exit",
    "forced_reason",
    "retention_obstruction",
    "repeated_confirmation",
    "channel_switch",
    "forced_contact",
    "delayed_execution",
    "redirect_loop",
    "dead_end",
    "unnecessary_form_burden",
    "information_overload",
    "policy_interface_mismatch",
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
LimitationCode = Literal[
    "captcha_required",
    "mfa_required",
    "email_verification_required",
    "credentials_required",
    "authentication_failed",
    "payment_required",
    "external_identity_provider",
    "bot_protection",
    "rate_limited",
    "channel_switch",
    "native_app_required",
    "goal_not_found",
    "selector_drift",
    "commit_blocked",
    "cross_origin_blocked",
    "runtime_budget_exhausted",
    "state_budget_exhausted",
    "navigation_failed",
    "cancelled",
    "model_unavailable",
]
AutomationStage = Literal[
    "queued",
    "validating",
    "static_scan",
    "site_crawl",
    "runtime_analysis",
    "discovering_acquisition",
    "establishing_session",
    "discovering_exit",
    "replaying",
    "scoring",
    "persisting",
    "needs_input",
    "completed",
    "failed",
    "cancelled",
]
AnalysisScope = Literal["single_page", "full_site"]
AutomationOutcome = Literal["candidate", "not_detected", "inconclusive", "needs_assistance"]
PublicationGate = Literal["auto_report", "report_with_caution", "inconclusive"]
FindingStatus = Literal["detected", "suspicious", "not_detected", "inconclusive"]
GraphPhase = Literal["acquisition", "session", "exit"]
RiskLevel = Literal["read_only", "reversible", "authentication", "mutating", "financial", "destructive"]
TransitionStatus = Literal["completed", "blocked", "failed", "frontier"]


class AutonomousCredentials(BaseModel):
    """Ephemeral credentials. Secret values must never enter persistence."""

    username: SecretStr = Field(min_length=1, max_length=320)
    password: SecretStr = Field(min_length=1, max_length=1024)
    login_url: AnyHttpUrl | None = None
    one_time_code: SecretStr | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("login_url")
    @classmethod
    def reject_login_url_secrets(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        return None if value is None else _reject_embedded_url_secrets(value, "login_url")


class AutonomousPolicy(BaseModel):
    max_states: int = Field(default=30, ge=5, le=60)
    max_depth: int = Field(default=6, ge=1, le=10)
    max_actions: int = Field(default=50, ge=5, le=120)
    max_runtime_seconds: int = Field(default=180, ge=30, le=600)
    max_candidates_per_state: int = Field(default=8, ge=1, le=15)
    replay_attempts: int = Field(default=2, ge=1, le=3)
    behavior_observation_seconds: int = Field(default=30, ge=5, le=90)
    max_pages: int = Field(default=60, ge=1, le=60)
    crawl_depth: int = Field(default=4, ge=0, le=8)


class AutonomousFlowRequest(BaseModel):
    url: AnyHttpUrl
    scope: AnalysisScope = "single_page"
    mode: FlowMode = "evidence_only"
    goal_families: list[GoalFamilyRequest] = Field(default_factory=lambda: ["auto"], min_length=1, max_length=10)
    credentials: AutonomousCredentials | None = None
    allowed_origins: list[str] = Field(default_factory=list, max_length=10)
    policy: AutonomousPolicy = Field(default_factory=AutonomousPolicy)
    analyse_models: bool = True
    analyse_behavior: bool = True

    @field_validator("url")
    @classmethod
    def reject_target_url_secrets(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        return _reject_embedded_url_secrets(value, "url")

    @field_validator("goal_families")
    @classmethod
    def normalize_goal_families(cls, values: list[GoalFamilyRequest]) -> list[GoalFamilyRequest]:
        unique = list(dict.fromkeys(values))
        if "auto" in unique and len(unique) > 1:
            raise ValueError("Use auto by itself or select explicit goal families.")
        return unique

    @field_validator("allowed_origins")
    @classmethod
    def validate_origins(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(_normalize_origin(value) for value in values))


class AutonomousFlowRequestSummary(BaseModel):
    """Safe representation returned by the API and stored in PostgreSQL."""

    url: str
    scope: AnalysisScope = "single_page"
    mode: FlowMode
    goal_families: list[GoalFamilyRequest]
    allowed_origins: list[str]
    policy: AutonomousPolicy
    analyse_models: bool
    analyse_behavior: bool = True
    has_credentials: bool

    @classmethod
    def from_request(cls, request: AutonomousFlowRequest) -> "AutonomousFlowRequestSummary":
        return cls(
            url=str(request.url),
            scope=request.scope,
            mode=request.mode,
            goal_families=request.goal_families,
            allowed_origins=request.allowed_origins,
            policy=request.policy,
            analyse_models=request.analyse_models,
            analyse_behavior=request.analyse_behavior,
            has_credentials=request.credentials is not None,
        )


class SelectorStrategy(BaseModel):
    kind: Literal["role", "label", "data_attribute", "id", "name", "css"]
    value: str = Field(max_length=1000)
    role: str | None = Field(default=None, max_length=80)
    accessible_name: str | None = Field(default=None, max_length=300)
    stable: bool = True


class ObservedControl(BaseModel):
    control_id: str
    role: str = Field(max_length=80)
    name: str = Field(max_length=300)
    href: str | None = Field(default=None, max_length=2000)
    input_type: str | None = Field(default=None, max_length=80)
    form_method: str | None = Field(default=None, max_length=20)
    required: bool = False
    disabled: bool = False
    selectors: list[SelectorStrategy] = Field(default_factory=list)
    presentation: TargetPresentation | None = None
    document_index: int = Field(default=0, ge=0)


class GraphNode(BaseModel):
    state_id: str
    fingerprint: str
    phase: GraphPhase
    url: str
    title: str
    headings: list[str] = Field(default_factory=list)
    dialog_text: str = ""
    depth: int = Field(ge=0)
    authentication_state: Literal["anonymous", "authenticated", "unknown"] = "unknown"
    screenshot_path: str | None = None
    controls: list[ObservedControl] = Field(default_factory=list)
    limitation_codes: list[LimitationCode] = Field(default_factory=list)


class GraphEdge(BaseModel):
    edge_id: str
    phase: GraphPhase
    source_state_id: str
    target_state_id: str | None = None
    action: str
    accessible_name: str
    selectors: list[SelectorStrategy] = Field(default_factory=list)
    risk: RiskLevel
    status: TransitionStatus
    duration_ms: int = Field(default=0, ge=0)
    page_transition: bool = False
    evidence_tags: list[str] = Field(default_factory=list)
    error: str | None = None


class StateGraph(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    root_state_ids: list[str] = Field(default_factory=list)


class AutomationLimitation(BaseModel):
    code: LimitationCode
    phase: GraphPhase | None = None
    message: str
    recoverable: bool = False
    state_id: str | None = None
    evidence: list[str] = Field(default_factory=list)


class GoalTerminalEvidence(BaseModel):
    verified: bool = False
    commit_frontier: bool = False
    confidence: float = Field(default=0, ge=0, le=1)
    state_id: str | None = None
    evidence: list[str] = Field(default_factory=list)


class AutonomousPathResult(BaseModel):
    phase: Literal["acquisition", "exit"]
    status: Literal["completed", "frontier", "failed", "not_found", "needs_input"]
    steps: list[FlowStepResult] = Field(default_factory=list)
    metrics: FlowMetrics
    state_ids: list[str] = Field(default_factory=list)
    terminal: GoalTerminalEvidence = Field(default_factory=GoalTerminalEvidence)
    required_fields: int = Field(default=0, ge=0)
    control_rank: int | None = Field(default=None, ge=1)


class AutonomousFinding(BaseModel):
    finding_id: str | None = None
    category: FindingCategory
    status: FindingStatus
    severity: Literal["none", "low", "medium", "high"]
    score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    evidence_refs: list[str] = Field(default_factory=list)
    rationale: str


class ConfidenceBreakdown(BaseModel):
    overall: float = Field(ge=0, le=1)
    goal_equivalence: float = Field(ge=0, le=1)
    acquisition_terminal: float = Field(ge=0, le=1)
    exit_terminal: float = Field(ge=0, le=1)
    replay_stability: float = Field(ge=0, le=1)
    selector_stability: float = Field(ge=0, le=1)
    evidence_quality: float = Field(ge=0, le=1)
    gate: PublicationGate
    review: Literal["not_needed", "optional", "recommended"]
    calibrated: bool = False
    reasons: list[str] = Field(default_factory=list)
    caps: list[str] = Field(default_factory=list)


class GoalPairAnalysis(BaseModel):
    goal_id: str
    family: GoalFamily
    signature: str
    label: str
    pairing_confidence: float = Field(ge=0, le=1)
    acquisition: AutonomousPathResult
    exit: AutonomousPathResult
    overall_finding: AutonomousFinding
    mechanism_findings: list[AutonomousFinding] = Field(default_factory=list)
    confidence_gate: ConfidenceBreakdown
    limitations: list[AutomationLimitation] = Field(default_factory=list)


class AutonomousRunSummary(BaseModel):
    goals_discovered: int = Field(ge=0)
    goals_completed: int = Field(ge=0)
    roach_motel_candidates: int = Field(ge=0)
    clean_goals: int = Field(ge=0)
    inconclusive_goals: int = Field(ge=0)
    outcome: AutomationOutcome
    confidence: float = Field(ge=0, le=1)
    gate: PublicationGate
    requires_assistance: bool = False
    behavioral_detected: int = Field(default=0, ge=0)
    behavioral_suspicious: int = Field(default=0, ge=0)
    pages_discovered: int = Field(default=0, ge=0)
    pages_scanned: int = Field(default=0, ge=0)
    pages_failed: int = Field(default=0, ge=0)


class SitePageAnalysis(BaseModel):
    url: str
    title: str = ""
    depth: int = Field(default=0, ge=0)
    discovered_from: str | None = None
    status: Literal["scanned", "failed", "skipped"]
    screenshot_path: str | None = None
    text_blocks_analyzed: int = Field(default=0, ge=0)
    text_findings: list[Finding] = Field(default_factory=list)
    visual_cues: list[VisualCue] = Field(default_factory=list)
    fusion_links: list[FusionLink] = Field(default_factory=list)
    frontend_behavior: FrontendBehaviorReport = Field(default_factory=FrontendBehaviorReport)
    discovered_goal_families: list[GoalFamily] = Field(default_factory=list)
    error: str | None = None


class SiteCrawlReport(BaseModel):
    status: Literal["not_requested", "completed", "completed_with_warnings"] = "not_requested"
    start_url: str = ""
    origin: str = ""
    pages_discovered: int = Field(default=0, ge=0)
    pages_scanned: int = Field(default=0, ge=0)
    pages_failed: int = Field(default=0, ge=0)
    max_pages_reached: bool = False
    max_depth_reached: bool = False
    coverage_complete: bool = False
    category_counts: dict[str, int] = Field(default_factory=dict)
    pages: list[SitePageAnalysis] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ModelPipelineStatus(BaseModel):
    bert: Literal["available", "unavailable", "not_requested"]
    yolo: Literal["available", "unavailable", "not_requested"]
    note: str = "Model outputs are supporting evidence and do not directly change flow effort."


class AutonomousFlowResult(BaseModel):
    run_id: str
    url: str
    pipeline_version: str
    summary: AutonomousRunSummary
    goals: list[GoalPairAnalysis] = Field(default_factory=list)
    graph: StateGraph
    limitations: list[AutomationLimitation] = Field(default_factory=list)
    model_status: ModelPipelineStatus
    frontend_behavior: FrontendBehaviorReport = Field(default_factory=FrontendBehaviorReport)
    site_audit: SiteCrawlReport = Field(default_factory=SiteCrawlReport)
    warnings: list[str] = Field(default_factory=list)


class AutonomousFlowJob(BaseModel):
    run_id: str
    kind: Literal["autonomous"] = "autonomous"
    status: Literal["queued", "running", "needs_input", "completed", "failed", "cancelled"]
    stage: AutomationStage
    progress: int = Field(ge=0, le=100)
    request: AutonomousFlowRequestSummary
    created_at: datetime
    updated_at: datetime
    result: AutonomousFlowResult | None = None
    error: str | None = None


class AutonomousInputRequest(BaseModel):
    credentials: AutonomousCredentials


class AutonomousFindingReviewRequest(BaseModel):
    decision: Literal["confirmed", "rejected", "needs_review"]
    severity: Literal["none", "low", "medium", "high"]
    notes: str = Field(default="", max_length=4000)


class AutonomousFindingReviewResponse(AutonomousFindingReviewRequest):
    id: str
    finding_id: str
    reviewer_id: str
    created_at: datetime
    updated_at: datetime


class AutonomousReviewQueueItem(BaseModel):
    run_id: str
    goal_id: str | None = None
    target_url: str
    goal_label: str | None = None
    publication_gate: PublicationGate
    review_recommendation: Literal["optional", "recommended"]
    finding: AutonomousFinding
    current_review: AutonomousFindingReviewResponse | None = None


class FlowComparisonRequest(BaseModel):
    baseline_run_id: str = Field(min_length=1, max_length=32)
    candidate_run_id: str = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def require_distinct_runs(self) -> "FlowComparisonRequest":
        if self.baseline_run_id == self.candidate_run_id:
            raise ValueError("baseline_run_id and candidate_run_id must be different")
        return self


class GoalRegression(BaseModel):
    signature: str
    verdict: Literal["improved", "unchanged", "regressed", "inconclusive"]
    acquisition_effort_delta: float
    exit_effort_delta: float
    effort_ratio_delta: float
    added_mechanisms: list[str] = Field(default_factory=list)
    resolved_mechanisms: list[str] = Field(default_factory=list)
    rationale: str


class BehaviorRegression(BaseModel):
    category: str
    verdict: Literal["improved", "unchanged", "regressed", "inconclusive"]
    baseline_status: str | None = None
    candidate_status: str | None = None
    confidence_delta: float = 0
    rationale: str


class FlowComparisonResult(BaseModel):
    comparison_id: str
    baseline_run_id: str
    candidate_run_id: str
    verdict: Literal["improved", "unchanged", "regressed", "inconclusive"]
    confidence: float = Field(ge=0, le=1)
    goal_regressions: list[GoalRegression] = Field(default_factory=list)
    behavior_regressions: list[BehaviorRegression] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime
