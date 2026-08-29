from __future__ import annotations

from pathlib import Path
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.service import get_current_user
from app.core.config import RUNTIME_DATA_DIR
from app.database import (
    FlowDefinitionRecord,
    FlowReviewRecord,
    get_database_session,
    utc_now,
)
from app.flow_analysis.discovery import discover_flow_candidates
from app.flow_analysis.jobs import FlowJobNotFoundError, flow_job_manager
from app.flow_analysis.presets import automation_exercise_account_lifecycle, local_benchmark
from app.flow_analysis.schemas import (
    FlowDefinitionCreate,
    FlowDefinitionResponse,
    FlowDiscoveryResponse,
    FlowJob,
    FlowPairRequest,
    FlowReviewRequest,
    FlowReviewResponse,
)
from app.schemas import UserPublic


router = APIRouter(prefix="/api/v1", tags=["flow-analysis"])


def _definition_response(record: FlowDefinitionRecord) -> FlowDefinitionResponse:
    payload = FlowDefinitionCreate.model_validate_json(record.definition_json)
    return FlowDefinitionResponse(
        id=record.id,
        owner_id=record.user_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
        **payload.model_dump(),
    )


@router.post("/flow-definitions", response_model=FlowDefinitionResponse, status_code=status.HTTP_201_CREATED)
def create_flow_definition(
    request: FlowDefinitionCreate,
    user: UserPublic = Depends(get_current_user),
    session: Session = Depends(get_database_session),
) -> FlowDefinitionResponse:
    record = FlowDefinitionRecord(
        id=str(uuid.uuid4()),
        user_id=user.id,
        name=request.name,
        definition_json=request.model_dump_json(),
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add(record)
    session.flush()
    return _definition_response(record)


@router.get("/flow-definitions", response_model=list[FlowDefinitionResponse])
def list_flow_definitions(
    user: UserPublic = Depends(get_current_user),
    session: Session = Depends(get_database_session),
) -> list[FlowDefinitionResponse]:
    records = session.scalars(
        select(FlowDefinitionRecord)
        .where(FlowDefinitionRecord.user_id == user.id)
        .order_by(FlowDefinitionRecord.created_at.desc())
    ).all()
    return [_definition_response(record) for record in records]


@router.post("/flow-runs", response_model=FlowJob, status_code=status.HTTP_202_ACCEPTED)
async def create_flow_run(request: FlowPairRequest, user: UserPublic = Depends(get_current_user)) -> FlowJob:
    return await flow_job_manager.create(request, user.id)


@router.post("/flow-runs/from-definition/{definition_id}", response_model=FlowJob, status_code=status.HTTP_202_ACCEPTED)
async def create_flow_from_definition(
    definition_id: str,
    user: UserPublic = Depends(get_current_user),
    session: Session = Depends(get_database_session),
) -> FlowJob:
    record = session.scalar(
        select(FlowDefinitionRecord).where(
            FlowDefinitionRecord.id == definition_id,
            FlowDefinitionRecord.user_id == user.id,
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Flow definition not found.")
    definition = FlowDefinitionCreate.model_validate_json(record.definition_json)
    return await flow_job_manager.create(definition.request, user.id, definition_id)


@router.post("/flow-runs/presets/automation-exercise", response_model=FlowJob, status_code=status.HTTP_202_ACCEPTED)
async def run_automation_exercise(user: UserPublic = Depends(get_current_user)) -> FlowJob:
    return await flow_job_manager.create(automation_exercise_account_lifecycle(), user.id)


@router.post("/flow-runs/presets/local/{variant}", response_model=FlowJob, status_code=status.HTTP_202_ACCEPTED)
async def run_local_benchmark(variant: str, user: UserPublic = Depends(get_current_user)) -> FlowJob:
    try:
        request = local_benchmark(variant)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return await flow_job_manager.create(request, user.id)


@router.get("/flow-runs", response_model=list[FlowJob])
async def list_flow_runs(
    limit: int = Query(default=50, ge=1, le=100),
    user: UserPublic = Depends(get_current_user),
) -> list[FlowJob]:
    return await flow_job_manager.list(user.id, limit)


@router.get("/flow-runs/{run_id}", response_model=FlowJob)
async def get_flow_run(run_id: str, user: UserPublic = Depends(get_current_user)) -> FlowJob:
    try:
        return await flow_job_manager.get(run_id, user.id)
    except FlowJobNotFoundError as error:
        raise HTTPException(status_code=404, detail="Flow run not found.") from error


@router.get("/flow-runs/{run_id}/screenshots/{filename}")
async def get_flow_screenshot(
    run_id: str,
    filename: str,
    user: UserPublic = Depends(get_current_user),
) -> FileResponse:
    try:
        await flow_job_manager.get(run_id, user.id)
    except FlowJobNotFoundError as error:
        raise HTTPException(status_code=404, detail="Flow run not found.") from error
    if Path(filename).name != filename or not filename.endswith(".png"):
        raise HTTPException(status_code=400, detail="Invalid screenshot name.")
    run_directory = (RUNTIME_DATA_DIR / "flow_runs" / run_id).resolve()
    target = (run_directory / filename).resolve()
    if target.parent != run_directory or not target.exists():
        raise HTTPException(status_code=404, detail="Screenshot not found.")
    return FileResponse(target, media_type="image/png")


def _review_response(record: FlowReviewRecord) -> FlowReviewResponse:
    return FlowReviewResponse(
        id=record.id,
        run_id=record.run_id,
        reviewer_id=record.user_id,
        decision=record.decision,
        severity=record.severity,
        notes=record.notes,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.put("/flow-runs/{run_id}/review", response_model=FlowReviewResponse)
async def review_flow_run(
    run_id: str,
    request: FlowReviewRequest,
    user: UserPublic = Depends(get_current_user),
    session: Session = Depends(get_database_session),
) -> FlowReviewResponse:
    try:
        job = await flow_job_manager.get(run_id, user.id)
    except FlowJobNotFoundError as error:
        raise HTTPException(status_code=404, detail="Flow run not found.") from error
    if job.status != "completed":
        raise HTTPException(status_code=409, detail="Only completed flow runs can be reviewed.")
    record = session.scalar(
        select(FlowReviewRecord).where(
            FlowReviewRecord.run_id == run_id,
            FlowReviewRecord.user_id == user.id,
        )
    )
    if record is None:
        record = FlowReviewRecord(run_id=run_id, user_id=user.id, **request.model_dump())
        session.add(record)
    else:
        for key, value in request.model_dump().items():
            setattr(record, key, value)
        record.updated_at = utc_now()
    session.flush()
    return _review_response(record)


@router.get("/flow-runs/{run_id}/reviews", response_model=list[FlowReviewResponse])
async def list_flow_reviews(
    run_id: str,
    user: UserPublic = Depends(get_current_user),
    session: Session = Depends(get_database_session),
) -> list[FlowReviewResponse]:
    try:
        await flow_job_manager.get(run_id, user.id)
    except FlowJobNotFoundError as error:
        raise HTTPException(status_code=404, detail="Flow run not found.") from error
    records = session.scalars(
        select(FlowReviewRecord)
        .where(FlowReviewRecord.run_id == run_id)
        .order_by(FlowReviewRecord.created_at)
    ).all()
    return [_review_response(record) for record in records]


@router.post("/flow-discovery", response_model=FlowDiscoveryResponse)
async def discover_flow_links(
    url: str = Query(min_length=8, max_length=2000),
    _user: UserPublic = Depends(get_current_user),
) -> FlowDiscoveryResponse:
    try:
        return await discover_flow_candidates(url)
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"Discovery failed: {type(error).__name__}: {error}") from error
