import asyncio
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, FlowFindingRecord, FlowRunRecord, FlowStepRecord, UserRecord
from app.flow_analysis import jobs
from app.flow_analysis.engine import FlowExecutionError, _allowed_origins, render_template
from app.flow_analysis.presets import local_benchmark
from app.flow_analysis.schemas import FlowRunResult, FlowStepEvidence, FlowStepResult
from app.flow_analysis.scoring import compare_flows, metrics_for_steps


def _step(index: int, *tags: str) -> FlowStepResult:
    return FlowStepResult(
        index=index,
        phase="exit",
        action="click",
        description=f"Step {index}",
        status="completed",
        url_before=f"https://example.com/{index}",
        url_after=f"https://example.com/{index + 1}",
        duration_ms=100,
        page_transition=True,
        evidence=FlowStepEvidence(obstruction_tags=list(tags)),
    )


def _run(name: str, steps: list[FlowStepResult]) -> FlowRunResult:
    phase = "acquisition" if name == "create" else "exit"
    steps = [step.model_copy(update={"phase": phase}) for step in steps]
    return FlowRunResult(
        name=name,
        goal=name,
        status="completed",
        steps=steps,
        metrics=metrics_for_steps(steps),
    )


def test_scoring_ignores_small_fair_difference() -> None:
    acquisition = _run("create", [_step(0)])
    exit_flow = _run("delete", [_step(0), _step(1)])

    finding = compare_flows(acquisition, exit_flow)

    assert finding.candidate is False
    assert finding.severity == "none"


def test_scoring_flags_obstructed_exit_with_evidence() -> None:
    acquisition = _run("create", [_step(0)])
    exit_flow = _run(
        "delete",
        [
            _step(0, "hidden_exit_control"),
            _step(1, "forced_reason"),
            _step(2, "retention_interstitial"),
            _step(3, "repeated_confirmation"),
            _step(4, "repeated_confirmation"),
        ],
    )

    finding = compare_flows(acquisition, exit_flow)

    assert finding.candidate is True
    assert finding.severity == "high"
    assert finding.score >= 70
    assert set(finding.evidence) == {
        "hidden_exit_control",
        "forced_reason",
        "retention_interstitial",
        "repeated_confirmation",
    }


def test_justified_warning_never_erases_baseline_actions() -> None:
    steps = [
        _step(0),
        _step(1),
    ]
    steps[0].evidence.justified_tags = ["irreversible_action_warning"]
    steps[1].evidence.justified_tags = ["irreversible_action_warning"]
    steps[1].url_after = steps[0].url_after

    metrics = metrics_for_steps(steps)

    assert metrics.justified_weight == 1.5
    assert metrics.effort_score >= 3.0


def test_templates_are_resolved_and_unresolved_values_fail() -> None:
    assert render_template("hello {{name}}", {"name": "researcher"}) == "hello researcher"
    with pytest.raises(FlowExecutionError, match="Unresolved flow variables"):
        render_template("{{missing}}", {})


def test_controlled_mode_rejects_unapproved_origins() -> None:
    request = local_benchmark("fair")
    request.allowed_origins = ["https://example.com"]
    with pytest.raises(FlowExecutionError, match="approved test origins"):
        _allowed_origins(request)


@pytest.mark.asyncio
async def test_completed_flow_job_persists_steps_and_finding(monkeypatch) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def test_scope():
        session: Session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    with test_scope() as session:
        user = UserRecord(email="flow-owner@example.com", password_hash="unused")
        session.add(user)
        session.flush()
        user_id = user.id

    request = local_benchmark("obstructed")

    async def fake_analysis(_request, run_id):
        acquisition = _run("create", [_step(0)])
        exit_flow = _run("delete", [_step(0, "forced_reason"), _step(1, "retention_interstitial")])
        from app.flow_analysis.schemas import FlowPairResult

        return FlowPairResult(
            run_id=run_id,
            name=request.name,
            source=request.source,
            mode=request.mode,
            acquisition=acquisition,
            exit=exit_flow,
            finding=compare_flows(acquisition, exit_flow),
        )

    monkeypatch.setattr(jobs, "session_scope", test_scope)
    monkeypatch.setattr(jobs, "perform_flow_analysis", fake_analysis)
    manager = jobs.PersistentFlowJobManager()
    created = await manager.create(request, user_id)

    for _ in range(50):
        stored = await manager.get(created.run_id, user_id)
        if stored.status == "completed":
            break
        await asyncio.sleep(0.01)

    assert stored.status == "completed"
    assert stored.result is not None
    with test_scope() as session:
        assert session.get(FlowRunRecord, created.run_id).result_json is not None
        assert len(session.scalars(select(FlowStepRecord)).all()) == 3
        assert len(session.scalars(select(FlowFindingRecord)).all()) == 1
