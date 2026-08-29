from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.auth.service import get_current_user
from app.core.config import RUNTIME_DATA_DIR
from app.database import (
    AutonomousFindingRecord,
    AutonomousFindingReviewRecord,
    AutonomousFlowRunRecord,
    FlowComparisonRecord,
    get_database_session,
    utc_now,
)
from app.flow_analysis.autonomous_jobs import (
    AutonomousFlowJobConflictError,
    AutonomousFlowJobNotFoundError,
    autonomous_flow_job_manager,
)
from app.flow_analysis.autonomous_schemas import (
    AutonomousFinding,
    AutonomousFindingReviewRequest,
    AutonomousFindingReviewResponse,
    AutonomousFlowJob,
    AutonomousFlowRequest,
    AutonomousFlowResult,
    AutonomousInputRequest,
    AutonomousReviewQueueItem,
    FlowComparisonRequest,
    FlowComparisonResult,
    StateGraph,
)
from app.flow_analysis.regression import compare_autonomous_results
from app.schemas import UserPublic


router = APIRouter(prefix="/api/v1", tags=["autonomous-flow-analysis"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Autonomous flow run not found.")


async def _owned_job(run_id: str, user_id: str) -> AutonomousFlowJob:
    try:
        return await autonomous_flow_job_manager.get(run_id, user_id)
    except AutonomousFlowJobNotFoundError as error:
        raise _not_found() from error


def _completed_result(job: AutonomousFlowJob) -> AutonomousFlowResult:
    if job.result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The autonomous flow result is not available yet.",
        )
    return job.result


def _review_response(record: AutonomousFindingReviewRecord) -> AutonomousFindingReviewResponse:
    return AutonomousFindingReviewResponse(
        id=record.id,
        finding_id=record.finding_id,
        reviewer_id=record.user_id,
        decision=record.decision,
        severity=record.severity,
        notes=record.notes,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _finding_response(record: AutonomousFindingRecord) -> AutonomousFinding:
    finding = AutonomousFinding.model_validate_json(record.finding_json)
    return finding.model_copy(update={"finding_id": record.id})


@router.post(
    "/flow-runs/autonomous",
    response_model=AutonomousFlowJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_autonomous_flow_run(
    request: AutonomousFlowRequest,
    user: UserPublic = Depends(get_current_user),
) -> AutonomousFlowJob:
    """Persist safe job metadata and immediately enqueue the browser worker."""

    return await autonomous_flow_job_manager.create(request, user.id)


@router.get("/autonomous-flow-runs", response_model=list[AutonomousFlowJob])
async def list_autonomous_flow_runs(
    limit: int = Query(default=50, ge=1, le=100),
    user: UserPublic = Depends(get_current_user),
) -> list[AutonomousFlowJob]:
    return await autonomous_flow_job_manager.list(user.id, limit)


@router.get("/autonomous-flow-runs/{run_id}", response_model=AutonomousFlowJob)
async def get_autonomous_flow_run(
    run_id: str,
    user: UserPublic = Depends(get_current_user),
) -> AutonomousFlowJob:
    return await _owned_job(run_id, user.id)


@router.get("/autonomous-flow-runs/{run_id}/graph", response_model=StateGraph)
async def get_autonomous_flow_graph(
    run_id: str,
    user: UserPublic = Depends(get_current_user),
) -> StateGraph:
    return _completed_result(await _owned_job(run_id, user.id)).graph


@router.get("/autonomous-flow-runs/{run_id}/findings", response_model=list[AutonomousFinding])
async def list_autonomous_flow_findings(
    run_id: str,
    user: UserPublic = Depends(get_current_user),
    session: Session = Depends(get_database_session),
) -> list[AutonomousFinding]:
    _completed_result(await _owned_job(run_id, user.id))
    records = session.scalars(
        select(AutonomousFindingRecord)
        .where(AutonomousFindingRecord.autonomous_run_id == run_id)
        .order_by(AutonomousFindingRecord.goal_id, AutonomousFindingRecord.category, AutonomousFindingRecord.id)
    ).all()
    return [_finding_response(record) for record in records]


@router.get("/autonomous-flow-runs/{run_id}/screenshots/{filename}")
async def get_autonomous_flow_screenshot(
    run_id: str,
    filename: str,
    user: UserPublic = Depends(get_current_user),
) -> FileResponse:
    await _owned_job(run_id, user.id)
    screenshot_root = (RUNTIME_DATA_DIR / "autonomous_flow_runs").resolve()
    run_directory = (screenshot_root / run_id).resolve()
    if run_directory.parent != screenshot_root:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Screenshot not found.")
    if Path(filename).name != filename or not filename.endswith(".png"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Screenshot not found.")
    target = (run_directory / filename).resolve()
    if target.parent != run_directory or not target.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Screenshot not found.")
    return FileResponse(target, media_type="image/png")


@router.post(
    "/autonomous-flow-runs/{run_id}/cancel",
    response_model=AutonomousFlowJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_autonomous_flow_run(
    run_id: str,
    user: UserPublic = Depends(get_current_user),
) -> AutonomousFlowJob:
    try:
        return await autonomous_flow_job_manager.cancel(run_id, user.id)
    except AutonomousFlowJobNotFoundError as error:
        raise _not_found() from error
    except AutonomousFlowJobConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post(
    "/autonomous-flow-runs/{run_id}/input",
    response_model=AutonomousFlowJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def continue_autonomous_flow_run(
    run_id: str,
    request: AutonomousInputRequest,
    user: UserPublic = Depends(get_current_user),
) -> AutonomousFlowJob:
    """Resume an input-blocked run; credential secrets remain worker-memory only."""

    try:
        return await autonomous_flow_job_manager.provide_credentials(run_id, user.id, request.credentials)
    except AutonomousFlowJobNotFoundError as error:
        raise _not_found() from error
    except AutonomousFlowJobConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.put(
    "/autonomous-findings/{finding_id}/review",
    response_model=AutonomousFindingReviewResponse,
)
def review_autonomous_finding(
    finding_id: str,
    request: AutonomousFindingReviewRequest,
    user: UserPublic = Depends(get_current_user),
    session: Session = Depends(get_database_session),
) -> AutonomousFindingReviewResponse:
    finding = session.scalar(
        select(AutonomousFindingRecord)
        .join(
            AutonomousFlowRunRecord,
            AutonomousFlowRunRecord.id == AutonomousFindingRecord.autonomous_run_id,
        )
        .where(
            AutonomousFindingRecord.id == finding_id,
            AutonomousFlowRunRecord.user_id == user.id,
        )
    )
    if finding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Autonomous finding not found.")

    record = session.scalar(
        select(AutonomousFindingReviewRecord).where(
            AutonomousFindingReviewRecord.finding_id == finding_id,
            AutonomousFindingReviewRecord.user_id == user.id,
        )
    )
    if record is None:
        record = AutonomousFindingReviewRecord(
            finding_id=finding_id,
            user_id=user.id,
            **request.model_dump(),
        )
        session.add(record)
    else:
        for key, value in request.model_dump().items():
            setattr(record, key, value)
        record.updated_at = utc_now()
    session.flush()
    return _review_response(record)


@router.get(
    "/autonomous-review-queue",
    response_model=list[AutonomousReviewQueueItem],
    include_in_schema=False,
)
@router.get("/autonomous-flow-review-queue", response_model=list[AutonomousReviewQueueItem])
def get_autonomous_review_queue(
    limit: int = Query(default=100, ge=1, le=200),
    user: UserPublic = Depends(get_current_user),
    session: Session = Depends(get_database_session),
) -> list[AutonomousReviewQueueItem]:
    rows = session.execute(
        select(AutonomousFindingRecord, AutonomousFlowRunRecord, AutonomousFindingReviewRecord)
        .join(
            AutonomousFlowRunRecord,
            AutonomousFlowRunRecord.id == AutonomousFindingRecord.autonomous_run_id,
        )
        .outerjoin(
            AutonomousFindingReviewRecord,
            and_(
                AutonomousFindingReviewRecord.finding_id == AutonomousFindingRecord.id,
                AutonomousFindingReviewRecord.user_id == user.id,
            ),
        )
        .where(AutonomousFlowRunRecord.user_id == user.id)
        .order_by(AutonomousFlowRunRecord.created_at.desc(), AutonomousFindingRecord.id)
    ).all()

    items: list[AutonomousReviewQueueItem] = []
    parsed_runs: dict[str, AutonomousFlowResult] = {}
    for finding_record, run_record, review_record in rows:
        if review_record is not None and review_record.decision in {"confirmed", "rejected"}:
            continue
        if run_record.result_json is None:
            continue
        result = parsed_runs.get(run_record.id)
        if result is None:
            result = _record_result(run_record)
            parsed_runs[run_record.id] = result
        goal = next((item for item in result.goals if item.goal_id == finding_record.goal_id), None)
        if goal is not None:
            if goal.confidence_gate.review == "not_needed":
                continue
            publication_gate = goal.confidence_gate.gate
            review_recommendation = goal.confidence_gate.review
            goal_label = goal.label
        else:
            behavior = next(
                (item for item in result.frontend_behavior.findings if item.finding_id == finding_record.id),
                None,
            )
            if behavior is None or behavior.status not in {"detected", "suspicious"} or behavior.confidence >= 0.85:
                continue
            publication_gate = "report_with_caution" if behavior.confidence >= 0.65 else "inconclusive"
            review_recommendation = "optional" if behavior.confidence >= 0.65 else "recommended"
            goal_label = f"Dynamic frontend: {behavior.category.replace('_', ' ').title()}"
        items.append(
            AutonomousReviewQueueItem(
                run_id=run_record.id,
                goal_id=finding_record.goal_id,
                target_url=run_record.target_url,
                goal_label=goal_label,
                publication_gate=publication_gate,
                review_recommendation=review_recommendation,
                finding=_finding_response(finding_record),
                current_review=None if review_record is None else _review_response(review_record),
            )
        )
        if len(items) >= limit:
            break
    return items


def _record_result(record: AutonomousFlowRunRecord) -> AutonomousFlowResult:
    return AutonomousFlowResult.model_validate_json(record.result_json)


@router.post(
    "/flow-comparisons",
    response_model=FlowComparisonResult,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
@router.post(
    "/autonomous-flow-comparisons",
    response_model=FlowComparisonResult,
    status_code=status.HTTP_201_CREATED,
)
async def create_autonomous_flow_comparison(
    request: FlowComparisonRequest,
    user: UserPublic = Depends(get_current_user),
    session: Session = Depends(get_database_session),
) -> FlowComparisonResult:
    if request.baseline_run_id == request.candidate_run_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Select two different runs.")
    baseline = _completed_result(await _owned_job(request.baseline_run_id, user.id))
    candidate = _completed_result(await _owned_job(request.candidate_run_id, user.id))

    record = session.scalar(
        select(FlowComparisonRecord).where(
            FlowComparisonRecord.user_id == user.id,
            FlowComparisonRecord.baseline_run_id == request.baseline_run_id,
            FlowComparisonRecord.candidate_run_id == request.candidate_run_id,
        )
    )
    comparison_id = record.id if record is not None else str(uuid.uuid4())
    comparison = compare_autonomous_results(baseline, candidate, comparison_id=comparison_id)
    if record is None:
        record = FlowComparisonRecord(
            id=comparison_id,
            user_id=user.id,
            baseline_run_id=request.baseline_run_id,
            candidate_run_id=request.candidate_run_id,
            verdict=comparison.verdict,
            confidence=comparison.confidence,
            result_json="",
            created_at=comparison.created_at,
        )
        session.add(record)
    else:
        comparison = comparison.model_copy(update={"created_at": record.created_at})
        record.verdict = comparison.verdict
        record.confidence = comparison.confidence
    record.result_json = comparison.model_dump_json()
    session.flush()
    return comparison


@router.get(
    "/flow-comparisons",
    response_model=list[FlowComparisonResult],
    include_in_schema=False,
)
@router.get("/autonomous-flow-comparisons", response_model=list[FlowComparisonResult])
def list_autonomous_flow_comparisons(
    limit: int = Query(default=50, ge=1, le=100),
    user: UserPublic = Depends(get_current_user),
    session: Session = Depends(get_database_session),
) -> list[FlowComparisonResult]:
    records = session.scalars(
        select(FlowComparisonRecord)
        .where(FlowComparisonRecord.user_id == user.id)
        .order_by(FlowComparisonRecord.created_at.desc())
        .limit(limit)
    ).all()
    return [FlowComparisonResult.model_validate_json(record.result_json) for record in records]
