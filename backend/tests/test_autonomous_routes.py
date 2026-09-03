from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import (
    AutonomousFindingRecord,
    AutonomousFlowRunRecord,
    Base,
    FlowComparisonRecord,
    UserRecord,
)
from app.flow_analysis import autonomous_routes
from app.flow_analysis.autonomous_schemas import (
    AutonomousCredentials,
    AutonomousFinding,
    AutonomousFindingReviewRequest,
    AutonomousFlowJob,
    AutonomousFlowRequest,
    AutonomousFlowRequestSummary,
    AutonomousFlowResult,
    AutonomousInputRequest,
    AutonomousPathResult,
    AutonomousRunSummary,
    ConfidenceBreakdown,
    FlowComparisonRequest,
    GoalPairAnalysis,
    ModelPipelineStatus,
    StateGraph,
)
from app.flow_analysis.schemas import FlowMetrics
from app.flow_analysis import pdf_report
from app.flow_analysis.pdf_report import build_report_html
from app.schemas import UserPublic


def _metrics(effort: float) -> FlowMetrics:
    return FlowMetrics(
        meaningful_actions=1,
        clicks=1,
        form_fields=0,
        page_transitions=1,
        active_time_ms=100,
        obstruction_weight=0,
        justified_weight=0,
        effort_score=effort,
        completed=True,
    )


def _result(run_id: str, effort: float = 2.0, review: str = "recommended") -> AutonomousFlowResult:
    gate = "inconclusive" if review == "recommended" else "report_with_caution"
    confidence = ConfidenceBreakdown(
        overall=0.6,
        goal_equivalence=0.8,
        acquisition_terminal=0.8,
        exit_terminal=0.6,
        replay_stability=0.5,
        selector_stability=0.9,
        evidence_quality=0.6,
        gate=gate,
        review=review,
    )
    finding = AutonomousFinding(
        finding_id="finding-1",
        category="roach_motel",
        status="inconclusive",
        severity="none",
        score=0,
        confidence=0.6,
        rationale="More evidence is required.",
    )
    acquisition = AutonomousPathResult(
        phase="acquisition",
        status="completed",
        metrics=_metrics(1.0),
    )
    exit_path = AutonomousPathResult(
        phase="exit",
        status="completed",
        metrics=_metrics(effort),
    )
    goal = GoalPairAnalysis(
        goal_id="goal-1",
        family="account_create_delete",
        signature="account:create-delete",
        label="Account lifecycle",
        pairing_confidence=0.9,
        acquisition=acquisition,
        exit=exit_path,
        overall_finding=finding,
        confidence_gate=confidence,
    )
    return AutonomousFlowResult(
        run_id=run_id,
        url="https://example.com",
        pipeline_version="test",
        summary=AutonomousRunSummary(
            goals_discovered=1,
            goals_completed=1,
            roach_motel_candidates=0,
            clean_goals=0,
            inconclusive_goals=1,
            outcome="inconclusive",
            confidence=0.6,
            gate=gate,
        ),
        goals=[goal],
        graph=StateGraph(),
        model_status=ModelPipelineStatus(bert="not_requested", yolo="not_requested"),
    )


def _job(run_id: str, result: AutonomousFlowResult | None = None, has_credentials: bool = False) -> AutonomousFlowJob:
    now = datetime.now(UTC)
    request = AutonomousFlowRequest(url="https://example.com")
    summary = AutonomousFlowRequestSummary.from_request(request).model_copy(
        update={"has_credentials": has_credentials}
    )
    return AutonomousFlowJob(
        run_id=run_id,
        status="completed" if result else "queued",
        stage="completed" if result else "queued",
        progress=100 if result else 0,
        request=summary,
        created_at=now,
        updated_at=now,
        result=result,
    )


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value


def _user(session: Session, user_id: str = "user-1") -> UserPublic:
    record = UserRecord(id=user_id, email=f"{user_id}@example.com", password_hash="unused")
    session.add(record)
    session.flush()
    return UserPublic(id=record.id, email=record.email, role="reviewer", created_at=record.created_at)


def _run_record(session: Session, user_id: str, result: AutonomousFlowResult) -> AutonomousFlowRunRecord:
    request = AutonomousFlowRequestSummary.from_request(AutonomousFlowRequest(url=result.url))
    record = AutonomousFlowRunRecord(
        id=result.run_id,
        user_id=user_id,
        target_url=result.url,
        target_origin="https://example.com",
        status="completed",
        stage="completed",
        progress=100,
        request_json=request.model_dump_json(),
        result_json=result.model_dump_json(),
        pipeline_version="test",
        outcome=result.summary.outcome,
        confidence=result.summary.confidence,
        cancellation_requested=False,
    )
    session.add(record)
    session.flush()
    return record


@pytest.mark.asyncio
async def test_create_returns_only_safe_request_summary(monkeypatch) -> None:
    captured = {}

    class FakeManager:
        async def create(self, request, user_id):
            captured["request"] = request
            return _job("auto-1", has_credentials=True)

    monkeypatch.setattr(autonomous_routes, "autonomous_flow_job_manager", FakeManager())
    user = UserPublic(id="user-1", email="one@example.com", role="reviewer", created_at=datetime.now(UTC))
    request = AutonomousFlowRequest(
        url="https://example.com",
        credentials=AutonomousCredentials(username="secret-user", password="super-secret-password"),
    )

    response = await autonomous_routes.create_autonomous_flow_run(request, user)

    payload = response.model_dump_json()
    assert captured["request"].credentials.password.get_secret_value() == "super-secret-password"
    assert "super-secret-password" not in payload
    assert "secret-user" not in payload
    assert response.request.has_credentials is True


def test_http_create_endpoint_returns_202_without_credentials(monkeypatch) -> None:
    class FakeManager:
        async def create(self, request, user_id):
            assert request.credentials.password.get_secret_value() == "super-secret-password"
            return _job("auto-http", has_credentials=True)

    monkeypatch.setattr(autonomous_routes, "autonomous_flow_job_manager", FakeManager())
    user = UserPublic(id="user-1", email="one@example.com", role="reviewer", created_at=datetime.now(UTC))
    app = FastAPI()
    app.include_router(autonomous_routes.router)
    app.dependency_overrides[autonomous_routes.get_current_user] = lambda: user

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/flow-runs/autonomous",
            json={
                "url": "https://example.com",
                "credentials": {"username": "secret-user", "password": "super-secret-password"},
            },
        )

    assert response.status_code == 202
    assert response.json()["request"]["has_credentials"] is True
    assert "super-secret-password" not in response.text
    assert "secret-user" not in response.text


@pytest.mark.asyncio
async def test_credentials_continuation_does_not_echo_secrets(monkeypatch) -> None:
    captured = {}

    class FakeManager:
        async def provide_credentials(self, run_id, user_id, credentials):
            captured.update(run_id=run_id, user_id=user_id, credentials=credentials)
            return _job(run_id, has_credentials=True)

    monkeypatch.setattr(autonomous_routes, "autonomous_flow_job_manager", FakeManager())
    user = UserPublic(id="user-1", email="one@example.com", role="reviewer", created_at=datetime.now(UTC))
    request = AutonomousInputRequest(
        credentials=AutonomousCredentials(username="private-user", password="private-password")
    )

    response = await autonomous_routes.continue_autonomous_flow_run("auto-1", request, user)

    payload = response.model_dump_json()
    assert captured["credentials"].username.get_secret_value() == "private-user"
    assert "private-user" not in payload
    assert "private-password" not in payload


@pytest.mark.asyncio
async def test_graph_and_findings_are_owner_scoped(monkeypatch, session: Session) -> None:
    user = _user(session)
    result = _result("auto-1")
    _run_record(session, user.id, result)
    finding = result.goals[0].overall_finding
    session.add(
        AutonomousFindingRecord(
            id=finding.finding_id,
            autonomous_run_id=result.run_id,
            goal_id=result.goals[0].goal_id,
            category=finding.category,
            status=finding.status,
            severity=finding.severity,
            score=finding.score,
            confidence=finding.confidence,
            finding_json=finding.model_dump_json(),
        )
    )
    session.flush()

    class FakeManager:
        async def get(self, run_id, user_id):
            assert (run_id, user_id) == ("auto-1", "user-1")
            return _job(run_id, result)

    monkeypatch.setattr(autonomous_routes, "autonomous_flow_job_manager", FakeManager())

    graph = await autonomous_routes.get_autonomous_flow_graph("auto-1", user)
    findings = await autonomous_routes.list_autonomous_flow_findings("auto-1", user, session)

    assert graph == result.graph
    assert [item.finding_id for item in findings] == ["finding-1"]


@pytest.mark.asyncio
async def test_screenshot_is_served_only_from_owned_run_directory(monkeypatch, tmp_path) -> None:
    runtime = tmp_path / "runtime"
    run_directory = runtime / "autonomous_flow_runs" / "auto-1"
    run_directory.mkdir(parents=True)
    screenshot = run_directory / "graph-001-exit.png"
    screenshot.write_bytes(b"png-test")

    class FakeManager:
        async def get(self, run_id, user_id):
            assert (run_id, user_id) == ("auto-1", "user-1")
            return _job(run_id)

    monkeypatch.setattr(autonomous_routes, "autonomous_flow_job_manager", FakeManager())
    monkeypatch.setattr(autonomous_routes, "RUNTIME_DATA_DIR", runtime)
    user = UserPublic(id="user-1", email="one@example.com", role="reviewer", created_at=datetime.now(UTC))

    response = await autonomous_routes.get_autonomous_flow_screenshot(
        "auto-1", "graph-001-exit.png", user
    )

    assert response.path == screenshot.resolve()
    assert response.media_type == "image/png"


def test_pdf_report_html_escapes_dynamic_content() -> None:
    result = _result("auto-report").model_copy(update={"url": "https://example.com/<script>alert(1)</script>"})
    finding = result.goals[0].overall_finding.model_copy(update={"rationale": "<img src=x onerror=alert(1)>"})
    result.goals[0].overall_finding = finding

    document = build_report_html(result)

    assert "FlowLens evidence report" in document
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in document
    assert "&lt;img src=x onerror=alert(1)&gt;" in document
    assert "<script>alert(1)</script>" not in document


def test_pdf_embeds_only_run_owned_png_evidence(monkeypatch, tmp_path) -> None:
    runtime = tmp_path / "runtime"
    run_directory = runtime / "autonomous_flow_runs" / "auto-report"
    run_directory.mkdir(parents=True)
    (run_directory / "inside.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    (runtime / "outside.png").write_bytes(b"\x89PNG\r\n\x1a\noutside")
    monkeypatch.setattr(pdf_report, "RUNTIME_DATA_DIR", runtime)

    embedded = pdf_report._evidence_image("C:/untrusted/path/inside.png", "auto-report")

    assert "data:image/png;base64," in embedded
    assert "inside.png" in embedded
    assert pdf_report._evidence_image("../outside.png", "auto-report") == ""
    assert pdf_report._evidence_image("inside.jpg", "auto-report") == ""


@pytest.mark.asyncio
async def test_pdf_report_download_is_owner_scoped(monkeypatch) -> None:
    result = _result("auto-report")

    class FakeManager:
        async def get(self, run_id, user_id):
            assert (run_id, user_id) == ("auto-report", "user-1")
            return _job(run_id, result)

    async def fake_renderer(value):
        assert value is result
        return b"%PDF-1.7\nbenchmark"

    monkeypatch.setattr(autonomous_routes, "autonomous_flow_job_manager", FakeManager())
    monkeypatch.setattr(autonomous_routes, "render_report_pdf", fake_renderer)
    user = UserPublic(id="user-1", email="one@example.com", role="reviewer", created_at=datetime.now(UTC))

    response = await autonomous_routes.download_autonomous_flow_report("auto-report", user)

    assert response.body.startswith(b"%PDF-1.7")
    assert response.media_type == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="flowlens-auto-report.pdf"'


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["../outside.png", "nested/inside.png", "evidence.jpg", "missing.png"])
async def test_screenshot_rejects_traversal_non_png_and_missing_files(
    monkeypatch,
    tmp_path,
    filename,
) -> None:
    runtime = tmp_path / "runtime"
    run_directory = runtime / "autonomous_flow_runs" / "auto-1"
    run_directory.mkdir(parents=True)
    (runtime / "autonomous_flow_runs" / "outside.png").write_bytes(b"outside")

    class FakeManager:
        async def get(self, run_id, user_id):
            return _job(run_id)

    monkeypatch.setattr(autonomous_routes, "autonomous_flow_job_manager", FakeManager())
    monkeypatch.setattr(autonomous_routes, "RUNTIME_DATA_DIR", runtime)
    user = UserPublic(id="user-1", email="one@example.com", role="reviewer", created_at=datetime.now(UTC))

    with pytest.raises(HTTPException) as error:
        await autonomous_routes.get_autonomous_flow_screenshot("auto-1", filename, user)

    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_screenshot_requires_run_ownership(monkeypatch, tmp_path) -> None:
    runtime = tmp_path / "runtime"
    run_directory = runtime / "autonomous_flow_runs" / "auto-1"
    run_directory.mkdir(parents=True)
    (run_directory / "private.png").write_bytes(b"private")

    class FakeManager:
        async def get(self, run_id, user_id):
            raise autonomous_routes.AutonomousFlowJobNotFoundError(run_id)

    monkeypatch.setattr(autonomous_routes, "autonomous_flow_job_manager", FakeManager())
    monkeypatch.setattr(autonomous_routes, "RUNTIME_DATA_DIR", runtime)
    other_user = UserPublic(
        id="user-2",
        email="two@example.com",
        role="reviewer",
        created_at=datetime.now(UTC),
    )

    with pytest.raises(HTTPException) as error:
        await autonomous_routes.get_autonomous_flow_screenshot("auto-1", "private.png", other_user)

    assert error.value.status_code == 404


def test_compatibility_aliases_are_registered_but_hidden_from_openapi() -> None:
    routes = {(route.path, tuple(sorted(route.methods or ()))): route for route in autonomous_routes.router.routes}

    assert routes[("/api/v1/autonomous-review-queue", ("GET",))].include_in_schema is False
    assert routes[("/api/v1/flow-comparisons", ("GET",))].include_in_schema is False
    assert routes[("/api/v1/flow-comparisons", ("POST",))].include_in_schema is False


def test_review_queue_and_finding_review(monkeypatch, session: Session) -> None:
    user = _user(session)
    result = _result("auto-1")
    _run_record(session, user.id, result)
    finding = result.goals[0].overall_finding
    session.add(
        AutonomousFindingRecord(
            id=finding.finding_id,
            autonomous_run_id=result.run_id,
            goal_id=result.goals[0].goal_id,
            category=finding.category,
            status=finding.status,
            severity=finding.severity,
            score=finding.score,
            confidence=finding.confidence,
            finding_json=finding.model_dump_json(),
        )
    )
    session.flush()

    queued = autonomous_routes.get_autonomous_review_queue(100, user, session)
    reviewed = autonomous_routes.review_autonomous_finding(
        "finding-1",
        AutonomousFindingReviewRequest(
            decision="confirmed",
            severity="medium",
            notes="Verified against the recorded journey.",
        ),
        user,
        session,
    )
    session.flush()
    after = autonomous_routes.get_autonomous_review_queue(100, user, session)

    assert len(queued) == 1
    assert queued[0].publication_gate == "inconclusive"
    assert queued[0].review_recommendation == "recommended"
    assert reviewed.finding_id == "finding-1"
    assert after == []


@pytest.mark.asyncio
async def test_comparisons_are_persisted_and_listed(monkeypatch, session: Session) -> None:
    user = _user(session)
    baseline_result = _result("baseline", effort=2.0, review="optional")
    candidate_result = _result("candidate", effort=5.0, review="optional")
    _run_record(session, user.id, baseline_result)
    _run_record(session, user.id, candidate_result)

    class FakeManager:
        async def get(self, run_id, user_id):
            assert user_id == "user-1"
            result = {"baseline": baseline_result, "candidate": candidate_result}[run_id]
            return _job(run_id, result)

    monkeypatch.setattr(autonomous_routes, "autonomous_flow_job_manager", FakeManager())
    request = FlowComparisonRequest(baseline_run_id="baseline", candidate_run_id="candidate")

    created = await autonomous_routes.create_autonomous_flow_comparison(request, user, session)
    session.flush()
    listed = autonomous_routes.list_autonomous_flow_comparisons(50, user, session)
    count = session.scalar(select(FlowComparisonRecord).where(FlowComparisonRecord.user_id == user.id))

    assert created.verdict == "regressed"
    assert [item.comparison_id for item in listed] == [created.comparison_id]
    assert count is not None
