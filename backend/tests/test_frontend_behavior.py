from __future__ import annotations

from pathlib import Path
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import pytest
from playwright.async_api import async_playwright

from app.core.config import configure_runtime_environment
from app.flow_analysis.autonomous_schemas import (
    AutonomousFlowRequest, AutonomousFlowResult, AutonomousRunSummary, ModelPipelineStatus, StateGraph,
)
from app.flow_analysis.benchmarks import fake_countdown_benchmark, genuine_countdown_benchmark, manipulative_store_benchmark
from app.flow_analysis.regression import compare_autonomous_results
from app.frontend_analysis.engine import _redact_text, _safe_url, _static_findings, analyze_frontend_behavior, parse_countdown_seconds
from app.frontend_analysis.schemas import FrontendArtifactSummary, FrontendBehaviorFinding, FrontendBehaviorReport


def test_parses_countdown_formats_without_accepting_arbitrary_numbers() -> None:
    assert parse_countdown_seconds("Ends in 01:02:03") == 3723
    assert parse_countdown_seconds("04:59") == 299
    assert parse_countdown_seconds("Only 42 left") is None


def test_behavior_schema_is_backward_compatible_for_stored_autonomous_runs() -> None:
    request = AutonomousFlowRequest(url="https://example.com")
    assert request.analyse_behavior is True
    assert request.policy.behavior_observation_seconds == 30

    old_result = {
        "run_id": "auto-old",
        "url": "https://example.com",
        "pipeline_version": "autonomous-roach-motel-v1",
        "summary": {
            "goals_discovered": 0, "goals_completed": 0, "roach_motel_candidates": 0,
            "clean_goals": 0, "inconclusive_goals": 0, "outcome": "inconclusive",
            "confidence": 0, "gate": "inconclusive",
        },
        "graph": {},
        "model_status": {"bert": "not_requested", "yolo": "not_requested"},
    }
    parsed = AutonomousFlowResult.model_validate(old_result)
    assert parsed.frontend_behavior.status == "not_requested"
    assert parsed.summary.behavioral_detected == 0


def test_static_frontend_evidence_covers_defaults_hierarchy_claims_and_disclosures() -> None:
    presentation = {"visible": True, "area": 100, "font_size": 9, "opacity": 0.4, "contrast": 2.0}
    initial = {
        "choices": [
            {"selector": "#marketing", "initially_selected": True, "text": "Partner marketing offers"},
            {"selector": "#insurance", "initially_selected": True, "text": "Device protection insurance ₹499"},
        ],
        "controls": [
            {"selector": ".accept", "text": "Accept all", "href": "", "presentation": {**presentation, "area": 1000, "font_size": 18, "opacity": 1, "contrast": 8}},
            {"selector": ".reject", "text": "Reject all", "href": "", "presentation": presentation},
            {"selector": ".continue", "text": "Continue", "href": "https://example.com/subscription-started", "presentation": presentation},
        ],
        "claims": [
            {"selector": ".stock", "text": "Only 2 left available", "presentation": presentation},
            {"selector": ".viewers", "text": "17 people are viewing this item", "presentation": presentation},
        ],
        "disclosures": [
            {"selector": ".terms", "text": "Recurring subscription at ₹999 per month and processing fee", "presentation": presentation},
        ],
    }
    clean = {"claims": initial["claims"]}
    findings = _static_findings(initial, clean, FrontendArtifactSummary())
    categories = {item.category: item for item in findings}

    assert categories.keys() >= {
        "preselected_option", "silent_cart_addition", "hidden_rejection", "fabricated_scarcity",
        "fabricated_social_proof", "misleading_action", "subscription_disclosure", "late_price_disclosure",
    }
    assert categories["fabricated_scarcity"].status == "suspicious"
    assert categories["preselected_option"].dark_pattern_category == "forced_consent"


def test_behavior_benchmark_pages_expose_genuine_fake_and_multi_pattern_controls() -> None:
    genuine = genuine_countdown_benchmark().body.decode()
    fake = fake_countdown_benchmark().body.decode()
    store = manipulative_store_benchmark().body.decode()

    assert "data-deadline" in genuine and "campaignDeadline" in genuine
    assert "let remaining = 8" in fake
    assert "Only 2 left" in store and "checked" in store and "Reject all" in store


def test_code_and_dom_evidence_models_store_hashes_and_redacted_excerpts_only() -> None:
    finding = _static_findings(
        {
            "choices": [], "claims": [], "disclosures": [],
            "controls": [{
                "selector": "#go", "text": "Continue", "href": "", "handler": "startSubscription('secret')",
                "presentation": {"visible": True, "area": 10, "font_size": 14, "opacity": 1, "contrast": 7},
            }],
        },
        {"claims": []},
        FrontendArtifactSummary(),
    )
    assert finding[0].category == "misleading_action"
    report = FrontendBehaviorReport()
    assert not hasattr(report.artifacts, "original_html")
    assert hasattr(report.artifacts, "original_html_sha256")
    assert "alice@example.com" not in _redact_text("user=alice@example.com token='top-secret'")
    safe_url = _safe_url("https://alice:password@example.com/orders/alice@example.com?token=secret&campaign=spring")
    assert "alice:password" not in safe_url
    assert "alice@example.com" not in safe_url
    assert "secret" not in safe_url
    assert "spring" not in safe_url


def test_regression_comparison_includes_dynamic_frontend_changes_without_flow_goals() -> None:
    def result(run_id: str, finding: FrontendBehaviorFinding) -> AutonomousFlowResult:
        return AutonomousFlowResult(
            run_id=run_id,
            url=f"https://example.com/{run_id}",
            pipeline_version="autonomous-flow-and-runtime-v2",
            summary=AutonomousRunSummary(
                goals_discovered=0, goals_completed=0, roach_motel_candidates=0, clean_goals=0,
                inconclusive_goals=0, outcome="candidate" if finding.status == "detected" else "not_detected",
                confidence=finding.confidence, gate="auto_report",
            ),
            graph=StateGraph(),
            model_status=ModelPipelineStatus(bert="not_requested", yolo="not_requested"),
            frontend_behavior=FrontendBehaviorReport(status="completed", findings=[finding]),
        )

    baseline_finding = FrontendBehaviorFinding(
        category="resetting_countdown", dark_pattern_category="false_urgency", status="not_detected",
        severity="none", score=0, confidence=.9, rationale="Shared deadline.",
    )
    candidate_finding = baseline_finding.model_copy(update={
        "status": "detected", "severity": "high", "score": 95, "confidence": .95,
        "rationale": "Reset across sessions.",
    })
    comparison = compare_autonomous_results(result("before", baseline_finding), result("after", candidate_finding))

    assert comparison.verdict == "regressed"
    assert comparison.confidence == .9
    assert comparison.behavior_regressions[0].category == "resetting_countdown"


@pytest.mark.asyncio
async def test_runtime_experiment_detects_a_resetting_non_expiring_timer(tmp_path: Path) -> None:
    configure_runtime_environment()
    html = """<!doctype html><title>Timer</title><p>Hurry, special offer!</p>
    <div id='timer'>00:03</div><p>Sale price remains available. Buy now.</p>
    <script>let remaining=3;const timer=document.querySelector('#timer');function tick(){timer.textContent=`00:${String(remaining).padStart(2,'0')}`;remaining--;if(remaining<0)remaining=3}tick();setInterval(tick,1000)</script>"""
    target = "data:text/html," + quote(html)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)

        async def context_factory():
            return await browser.new_context(viewport={"width": 900, "height": 600})

        report = await analyze_frontend_behavior(
            browser, target, context_factory, tmp_path, observation_seconds=5, analyse_models=False
        )
        await browser.close()

    timer = next(item for item in report.findings if item.category == "resetting_countdown")
    assert timer.status == "detected"
    assert timer.dark_pattern_category == "false_urgency"
    assert timer.after_reload is not None and timer.clean_session_value is not None
    assert any("restarted" in evidence or "Reloading" in evidence for evidence in timer.evidence)
    assert len(report.dom_snapshots) == 4
    assert report.artifacts.rendered_dom_sha256
    assert any(item.category == "non_expiring_offer" and item.status == "detected" for item in report.findings)


@pytest.mark.asyncio
async def test_runtime_experiment_recognizes_a_shared_absolute_deadline(tmp_path: Path) -> None:
    configure_runtime_environment()
    deadline = (datetime.now(UTC) + timedelta(seconds=60)).isoformat()
    html = f"""<!doctype html><title>Genuine</title><p>Scheduled campaign</p><div id='timer' data-deadline='{deadline}'>01:00</div>
    <script>const deadline='{deadline}';const campaignDeadline=new Date(deadline);const timer=document.querySelector('#timer');function tick(){{const left=Math.max(0,Math.floor((campaignDeadline-Date.now())/1000));timer.textContent=`00:${{String(left).padStart(2,'0')}}`}}tick();setInterval(tick,1000)</script>"""
    target = "data:text/html," + quote(html)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)

        async def context_factory():
            return await browser.new_context(viewport={"width": 900, "height": 600})

        report = await analyze_frontend_behavior(
            browser, target, context_factory, tmp_path, observation_seconds=5, analyse_models=False
        )
        await browser.close()

    timer = next(item for item in report.findings if item.category == "resetting_countdown")
    assert timer.status == "not_detected"
    assert timer.implementation_signal == "absolute_deadline"
