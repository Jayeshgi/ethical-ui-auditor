from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from app.flow_analysis.autonomous_jobs import PersistentAutonomousFlowJobManager, _redact_error
from app.flow_analysis.autonomous_schemas import (
    AutonomousCredentials,
    AutonomousFinding,
    AutonomousFlowRequest,
    AutonomousFlowRequestSummary,
    AutonomousFlowResult,
    AutonomousPathResult,
    AutonomousRunSummary,
    FlowComparisonRequest,
    GoalPairAnalysis,
    GoalTerminalEvidence,
    GraphEdge,
    GraphNode,
    ModelPipelineStatus,
    ObservedControl,
    SelectorStrategy,
    StateGraph,
)
from app.flow_analysis.autonomous_scoring import roach_motel_finding
from app.flow_analysis.confidence import build_confidence_breakdown
from app.flow_analysis.mechanisms import detect_mechanisms
from app.flow_analysis.observation import redact_observed_text, redact_observed_url
from app.flow_analysis.limitations import _clean_excerpt, detect_limitations
from app.flow_analysis.observation import redact_observed_text
from app.flow_analysis.regression import compare_autonomous_results
from app.flow_analysis.selectors import locator_for_strategy
from app.flow_analysis.schemas import FlowMetrics, FlowStepEvidence, FlowStepResult, TargetPresentation


def _metrics(effort: float, *, completed: bool = True) -> FlowMetrics:
    return FlowMetrics(
        meaningful_actions=max(0, int(effort)),
        clicks=max(0, int(effort)),
        form_fields=0,
        page_transitions=0,
        active_time_ms=0,
        obstruction_weight=0,
        justified_weight=0,
        effort_score=effort,
        completed=completed,
    )


def _path(
    phase: str,
    effort: float,
    *,
    state_ids: list[str] | None = None,
    terminal: GoalTerminalEvidence | None = None,
    required_fields: int = 0,
    control_rank: int | None = None,
    steps: list[FlowStepResult] | None = None,
) -> AutonomousPathResult:
    return AutonomousPathResult(
        phase=phase,
        status="completed",
        steps=steps or [],
        metrics=_metrics(effort),
        state_ids=state_ids or [],
        terminal=terminal or GoalTerminalEvidence(verified=True, confidence=1.0),
        required_fields=required_fields,
        control_rank=control_rank,
    )


def _node(state_id: str, text: str, controls: list[ObservedControl] | None = None) -> GraphNode:
    return GraphNode(
        state_id=state_id,
        fingerprint=f"fingerprint-{state_id}",
        phase="exit",
        url=f"https://example.com/{state_id}",
        title="Exit",
        headings=[text],
        depth=1,
        controls=controls or [],
    )


def _confidence(value: float = 0.95):
    return build_confidence_breakdown(
        goal_equivalence=value,
        acquisition_terminal=GoalTerminalEvidence(verified=True, confidence=value),
        exit_terminal=GoalTerminalEvidence(verified=True, confidence=value),
        replay_attempts=2,
        replay_successes=2,
        selector_stability=value,
        evidence_quality=value,
    )


def _mechanism(category: str = "forced_reason") -> AutonomousFinding:
    return AutonomousFinding(
        category=category,
        status="detected",
        severity="low",
        score=14,
        confidence=0.9,
        evidence_refs=["state:exit"],
        rationale="Structural exit evidence.",
    )


def _result(
    run_id: str,
    *,
    url: str = "https://example.com/settings",
    pipeline_version: str = "autonomous-roach-motel-v1",
    exit_effort: float = 8,
    mechanisms: list[AutonomousFinding] | None = None,
    include_goal: bool = True,
) -> AutonomousFlowResult:
    confidence = _confidence()
    acquisition = _path("acquisition", 2)
    exit_path = _path("exit", exit_effort)
    mechanism_findings = mechanisms if mechanisms is not None else [_mechanism()]
    overall = roach_motel_finding(acquisition, exit_path, mechanism_findings, confidence, 0.95)
    goals = []
    if include_goal:
        goals.append(
            GoalPairAnalysis(
                goal_id=f"goal-{run_id}",
                family="account_create_delete",
                signature="account_create_delete:default",
                label="Account",
                pairing_confidence=0.95,
                acquisition=acquisition,
                exit=exit_path,
                overall_finding=overall,
                mechanism_findings=mechanism_findings,
                confidence_gate=confidence,
            )
        )
    return AutonomousFlowResult(
        run_id=run_id,
        url=url,
        pipeline_version=pipeline_version,
        summary=AutonomousRunSummary(
            goals_discovered=len(goals),
            goals_completed=len(goals),
            roach_motel_candidates=int(bool(goals and overall.status == "detected")),
            clean_goals=0,
            inconclusive_goals=0,
            outcome="candidate" if goals else "inconclusive",
            confidence=confidence.overall if goals else 0,
            gate=confidence.gate if goals else "inconclusive",
        ),
        goals=goals,
        graph=StateGraph(),
        model_status=ModelPipelineStatus(bert="not_requested", yolo="not_requested"),
    )


def test_request_summary_never_serializes_ephemeral_credentials() -> None:
    request = AutonomousFlowRequest(
        url="https://example.com/account",
        credentials=AutonomousCredentials(
            username="student@example.com",
            password="correct horse battery staple",
            one_time_code="987654",
        ),
    )

    serialized = AutonomousFlowRequestSummary.from_request(request).model_dump_json()

    assert "student@example.com" not in serialized
    assert "correct horse battery staple" not in serialized
    assert "987654" not in serialized
    assert "password" not in serialized
    assert '"has_credentials":true' in serialized


def test_observation_redacts_explicit_credentials_and_common_pii() -> None:
    text = redact_observed_text(
        "Welcome AlicePrivate alice@example.com card 4111 1111 1111 1111",
        ["AlicePrivate"],
    )
    url = redact_observed_url(
        "https://example.com/AlicePrivate?token=secret&email=alice@example.com#private",
        ["AlicePrivate", "secret"],
    )

    assert "AlicePrivate" not in text
    assert "alice@example.com" not in text
    assert "4111" not in text
    assert url is not None
    assert "AlicePrivate" not in url
    assert "secret" not in url
    assert "alice@example.com" not in url
    assert "#private" not in url


@pytest.mark.parametrize(
    "url",
    [
        "https://student:secret@example.com/account",
        "https://example.com/account?access_token=super-secret",
        "https://example.com/account?sessionId=super-secret",
    ],
)
def test_request_rejects_credentials_embedded_in_persisted_url(url: str) -> None:
    with pytest.raises(ValidationError, match="must not contain"):
        AutonomousFlowRequest(url=url)


def test_allowed_origins_are_exact_and_canonical() -> None:
    request = AutonomousFlowRequest(
        url="https://example.com/account",
        allowed_origins=["HTTPS://EXAMPLE.COM:443/", "http://localhost:8000"],
    )
    assert request.allowed_origins == ["https://example.com", "http://localhost:8000"]

    with pytest.raises(ValidationError, match="only scheme, host"):
        AutonomousFlowRequest(url="https://example.com", allowed_origins=["https://example.com/private"])


def test_comparison_rejects_comparing_a_run_with_itself() -> None:
    with pytest.raises(ValidationError, match="must be different"):
        FlowComparisonRequest(baseline_run_id="auto-one", candidate_run_id="auto-one")


def test_persisted_id_and_name_values_cannot_inject_selector_lists() -> None:
    class FakePage:
        def __init__(self) -> None:
            self.selectors: list[str] = []

        def locator(self, selector: str):
            self.selectors.append(selector)
            return selector

    page = FakePage()
    locator_for_strategy(page, SelectorStrategy(kind="id", value='[id="safe"],button'))
    locator_for_strategy(page, SelectorStrategy(kind="name", value='email"], a[href="/delete"]'))

    assert page.selectors == [
        '[id="[id=\\"safe\\"],button"]',
        '[name="email\\"], a[href=\\"/delete\\"]"]',
    ]


def test_error_redaction_covers_every_ephemeral_secret() -> None:
    request = AutonomousFlowRequest(
        url="https://example.com",
        credentials=AutonomousCredentials(username="alice", password="p@ssword", one_time_code="112233"),
    )
    error = RuntimeError("login alice with p@ssword and OTP 112233 failed")
    redacted = _redact_error(error, request)
    assert "alice" not in redacted
    assert "p@ssword" not in redacted
    assert "112233" not in redacted
    assert redacted.count("[REDACTED]") == 3


def test_persisted_limitation_evidence_redacts_personal_data() -> None:
    limitations = detect_limitations(
        "Authentication failed for student@example.com; call +91 98765 43210 for help.",
        phase="session",
    )
    serialized = " ".join(item.model_dump_json() for item in limitations)

    assert "student@example.com" not in serialized
    assert "98765 43210" not in serialized
    excerpt = _clean_excerpt("student@example.com +91 98765 43210 4111 1111 1111 1111")
    assert "student@example.com" not in excerpt
    assert "98765 43210" not in excerpt
    assert "4111 1111 1111 1111" not in excerpt
    assert "[REDACTED_EMAIL]" in excerpt
    assert "[REDACTED_NUMBER]" in excerpt
    observed = redact_observed_text("Card 4111 1111 1111 1111; phone +91 98765 43210")
    assert "4111" not in observed
    assert "98765" not in observed


@pytest.mark.asyncio
async def test_cancelled_before_worker_start_drops_ephemeral_request(monkeypatch) -> None:
    manager = PersistentAutonomousFlowJobManager()
    request = AutonomousFlowRequest(
        url="https://example.com",
        credentials=AutonomousCredentials(username="alice", password="secret"),
    )

    async def blocked(_run_id, _request):
        await asyncio.Event().wait()

    monkeypatch.setattr(manager, "_execute", blocked)
    manager._ephemeral_requests["auto-test"] = request
    manager._schedule("auto-test", request)
    task = manager._tasks["auto-test"]
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)

    assert "auto-test" not in manager._ephemeral_requests
    assert "auto-test" not in manager._tasks


def test_mechanism_detection_covers_structural_graph_and_step_evidence() -> None:
    reason = ObservedControl(
        control_id="reason",
        role="textbox",
        name="Why are you leaving?",
        input_type="text",
        required=True,
    )
    hidden_step = FlowStepResult(
        index=2,
        phase="exit",
        action="click",
        description="Continue cancellation",
        status="completed",
        url_before="https://example.com/a",
        url_after="https://example.com/b",
        duration_ms=10,
        page_transition=True,
        evidence=FlowStepEvidence(
            target_presentation=TargetPresentation(
                visible=True,
                opacity=0.2,
                font_size_px=9,
                viewport_area_ratio=0.00001,
            )
        ),
    )
    nodes = [
        _node("confirm-1", "Are you sure? Special offer before you go", [reason]),
        _node("confirm-2", "Confirm deletion"),
        _node("contact", "You must speak to an agent. Call us to cancel."),
        _node("delay", "Deletion may take 30 business days"),
    ]
    edge = GraphEdge(
        edge_id="policy-edge",
        phase="exit",
        source_state_id="confirm-1",
        target_state_id="confirm-2",
        action="click",
        accessible_name="Continue",
        risk="reversible",
        status="completed",
        evidence_tags=["policy_interface_mismatch"],
    )
    acquisition = _path("acquisition", 2, required_fields=0)
    exit_path = _path(
        "exit",
        12,
        state_ids=[node.state_id for node in nodes],
        required_fields=3,
        control_rank=20,
        steps=[hidden_step],
    )

    findings = detect_mechanisms(
        acquisition,
        exit_path,
        nodes,
        [edge],
        loop_state_ids=["confirm-1"],
        dead_end_state_ids=["contact"],
    )
    categories = {finding.category for finding in findings}

    assert categories == {
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
    }
    hidden = next(item for item in findings if item.category == "hidden_exit")
    assert hidden.evidence_refs == ["step:2:target-presentation"]


def test_generic_support_discount_and_shipping_copy_are_not_exit_mechanisms() -> None:
    nodes = [
        _node("support", "Stay secure and call us for general support"),
        _node("shipping", "Shipping may take 30 business days and includes a discount"),
    ]
    findings = detect_mechanisms(
        _path("acquisition", 2),
        _path("exit", 3, state_ids=[node.state_id for node in nodes]),
        nodes,
        [],
    )

    assert findings == []


def test_roach_motel_requires_equivalence_terminals_and_direct_mechanism() -> None:
    acquisition = _path("acquisition", 2)
    exit_path = _path("exit", 10)
    confidence = _confidence()

    detected = roach_motel_finding(acquisition, exit_path, [_mechanism()], confidence, 0.95)
    no_mechanism = roach_motel_finding(acquisition, exit_path, [], confidence, 0.95)
    weak_pair = roach_motel_finding(acquisition, exit_path, [_mechanism()], confidence, 0.4)

    assert detected.status == "detected"
    assert detected.severity == "high"
    assert no_mechanism.status == "not_detected"
    assert weak_pair.status == "inconclusive"
    assert weak_pair.score <= 35


def test_regression_normalizes_default_ports_and_detects_added_obstruction() -> None:
    baseline = _result("base", url="https://EXAMPLE.com:443/account", exit_effort=4, mechanisms=[])
    candidate = _result(
        "candidate",
        url="https://example.com/settings",
        exit_effort=9,
        mechanisms=[_mechanism("forced_reason")],
    )

    comparison = compare_autonomous_results(baseline, candidate, comparison_id="comparison")

    assert comparison.warnings == []
    assert comparison.verdict == "regressed"
    assert comparison.confidence > 0.85
    assert comparison.goal_regressions[0].added_mechanisms == ["forced_reason"]


def test_regression_matches_one_unambiguous_family_across_redesigned_routes() -> None:
    baseline = _result("base", exit_effort=4, mechanisms=[])
    candidate = _result("candidate", exit_effort=9, mechanisms=[_mechanism("forced_reason")])
    candidate.goals[0].signature = "account_create_delete:route-redesigned"

    comparison = compare_autonomous_results(baseline, candidate)

    assert comparison.verdict == "regressed"
    assert comparison.goal_regressions[0].signature == "account_create_delete:unique-family-match"
    assert "matched across a changed object signature" in comparison.goal_regressions[0].rationale


def test_regression_is_inconclusive_across_pipeline_versions_or_missing_goals() -> None:
    baseline = _result("base")
    changed_pipeline = _result("candidate", pipeline_version="autonomous-roach-motel-v2")
    comparison = compare_autonomous_results(baseline, changed_pipeline)
    assert comparison.verdict == "inconclusive"
    assert comparison.confidence == 0
    assert any("pipeline versions" in warning for warning in comparison.warnings)

    missing = compare_autonomous_results(baseline, _result("candidate-2", include_goal=False))
    assert missing.verdict == "inconclusive"
    assert missing.confidence <= 0.49
