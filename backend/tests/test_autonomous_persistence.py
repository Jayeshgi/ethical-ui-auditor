from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import AutonomousFindingRecord, Base, FlowGoalRecord, UserRecord
from app.flow_analysis import autonomous_jobs
from app.flow_analysis.autonomous_schemas import (
    AutonomousFinding,
    AutonomousFlowRequest,
    AutonomousFlowRequestSummary,
    AutonomousFlowResult,
    AutonomousPathResult,
    AutonomousRunSummary,
    ConfidenceBreakdown,
    GoalPairAnalysis,
    GoalTerminalEvidence,
    ModelPipelineStatus,
    StateGraph,
)
from app.flow_analysis.schemas import FlowMetrics


def _path(phase: str, effort: float) -> AutonomousPathResult:
    return AutonomousPathResult(
        phase=phase,
        status="completed",
        metrics=FlowMetrics(
            meaningful_actions=1,
            clicks=1,
            form_fields=0,
            page_transitions=1,
            active_time_ms=10,
            obstruction_weight=0,
            justified_weight=0,
            effort_score=effort,
            completed=True,
        ),
        terminal=GoalTerminalEvidence(verified=True, confidence=1),
    )


def test_result_persistence_flushes_goal_before_findings(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def test_scope():
        with factory() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    monkeypatch.setattr(autonomous_jobs, "session_scope", test_scope)
    with test_scope() as session:
        user = UserRecord(email="autonomous-owner@example.com", password_hash="unused")
        session.add(user)
        session.flush()
        user_id = user.id

    request = AutonomousFlowRequest(url="https://example.com")
    autonomous_jobs.PersistentAutonomousFlowJobManager._create_record(
        "auto-fk-order",
        AutonomousFlowRequestSummary.from_request(request),
        user_id,
    )
    confidence = ConfidenceBreakdown(
        overall=0.9,
        goal_equivalence=0.9,
        acquisition_terminal=1,
        exit_terminal=1,
        replay_stability=1,
        selector_stability=1,
        evidence_quality=0.9,
        gate="auto_report",
        review="not_needed",
    )
    finding = AutonomousFinding(
        category="roach_motel",
        status="not_detected",
        severity="none",
        score=0,
        confidence=0.9,
        rationale="Equivalent journeys have equal effort.",
    )
    goal = GoalPairAnalysis(
        goal_id="goal-fk-order",
        family="account_create_delete",
        signature="account_create_delete:test",
        label="Account lifecycle",
        pairing_confidence=0.9,
        acquisition=_path("acquisition", 1),
        exit=_path("exit", 1),
        overall_finding=finding,
        confidence_gate=confidence,
    )
    result = AutonomousFlowResult(
        run_id="auto-fk-order",
        url="https://example.com",
        pipeline_version=autonomous_jobs.AUTONOMOUS_PIPELINE_VERSION,
        summary=AutonomousRunSummary(
            goals_discovered=1,
            goals_completed=1,
            roach_motel_candidates=0,
            clean_goals=1,
            inconclusive_goals=0,
            outcome="not_detected",
            confidence=0.9,
            gate="auto_report",
        ),
        goals=[goal],
        graph=StateGraph(),
        model_status=ModelPipelineStatus(bert="not_requested", yolo="not_requested"),
    )

    persisted = autonomous_jobs.PersistentAutonomousFlowJobManager._store_result(
        "auto-fk-order", result
    )

    assert persisted.goals[0].overall_finding.finding_id is not None
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(FlowGoalRecord)) == 1
        assert session.scalar(select(func.count()).select_from(AutonomousFindingRecord)) == 1
