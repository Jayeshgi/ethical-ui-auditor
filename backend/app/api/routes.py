from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.service import get_current_user
from app.core.security import UnsafeUrlError
from app.database import ReviewRecord, get_database_session, utc_now
from app.schemas import (
    ReviewRequest,
    ReviewResponse,
    ScanComparison,
    ScanJob,
    ScanRequest,
    ScanResponse,
    UserPublic,
)
from app.scans.jobs import ScanJobNotFoundError, scan_job_manager
from app.scans.service import BrowserScanError, perform_scan
from app.text_analysis.model import ModelUnavailableError


router = APIRouter(prefix="/api/v1", tags=["scans"])


@router.post("/scans", response_model=ScanJob, status_code=status.HTTP_202_ACCEPTED)
async def create_scan(request: ScanRequest, user: UserPublic = Depends(get_current_user)) -> ScanJob:
    """Queue a durable scan owned by the authenticated user."""
    return await scan_job_manager.create(request, user.id)


@router.get("/scans", response_model=list[ScanJob])
async def list_scans(
    limit: int = Query(default=50, ge=1, le=100),
    user: UserPublic = Depends(get_current_user),
) -> list[ScanJob]:
    return await scan_job_manager.list(user.id, limit)


def _counts(job: ScanJob) -> tuple[Counter, Counter]:
    text_counts, visual_counts = Counter(), Counter()
    if job.result:
        for page in job.result.pages:
            text_counts.update(finding.category for finding in page.findings)
            visual_counts.update(cue.cue for cue in page.visual_cues)
    return text_counts, visual_counts


@router.get("/scans/compare", response_model=ScanComparison)
async def compare_scans(
    left_scan_id: str,
    right_scan_id: str,
    user: UserPublic = Depends(get_current_user),
) -> ScanComparison:
    try:
        left = await scan_job_manager.get(left_scan_id, user.id)
        right = await scan_job_manager.get(right_scan_id, user.id)
    except ScanJobNotFoundError as error:
        raise HTTPException(status_code=404, detail="One or both scan jobs were not found.") from error
    if left.status != "completed" or right.status != "completed":
        raise HTTPException(status_code=409, detail="Both scans must be completed before comparison.")
    left_text, left_visual = _counts(left)
    right_text, right_visual = _counts(right)
    text_keys, visual_keys = set(left_text) | set(right_text), set(left_visual) | set(right_visual)
    return ScanComparison(
        left_scan_id=left.scan_id,
        right_scan_id=right.scan_id,
        left_text_categories=dict(left_text),
        right_text_categories=dict(right_text),
        text_category_delta={key: right_text[key] - left_text[key] for key in sorted(text_keys)},
        left_visual_cues=dict(left_visual),
        right_visual_cues=dict(right_visual),
        visual_cue_delta={key: right_visual[key] - left_visual[key] for key in sorted(visual_keys)},
    )


@router.get("/scans/{scan_id}", response_model=ScanJob)
async def get_scan(scan_id: str, user: UserPublic = Depends(get_current_user)) -> ScanJob:
    try:
        return await scan_job_manager.get(scan_id, user.id)
    except ScanJobNotFoundError as error:
        raise HTTPException(status_code=404, detail="Scan job not found.") from error


def _review_response(record: ReviewRecord) -> ReviewResponse:
    return ReviewResponse(
        id=record.id,
        scan_id=record.scan_id,
        reviewer_id=record.user_id,
        page_index=record.page_index,
        evidence_type=record.evidence_type,
        evidence_index=record.evidence_index,
        decision=record.decision,
        severity=record.severity,
        notes=record.notes,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.put("/scans/{scan_id}/reviews", response_model=ReviewResponse)
async def upsert_review(
    scan_id: str,
    request: ReviewRequest,
    user: UserPublic = Depends(get_current_user),
    session: Session = Depends(get_database_session),
) -> ReviewResponse:
    try:
        job = await scan_job_manager.get(scan_id, user.id)
    except ScanJobNotFoundError as error:
        raise HTTPException(status_code=404, detail="Scan job not found.") from error
    if job.result is None or job.status != "completed":
        raise HTTPException(status_code=409, detail="Only completed scan evidence can be reviewed.")
    if request.page_index >= len(job.result.pages):
        raise HTTPException(status_code=422, detail="page_index is outside the scan result.")
    page = job.result.pages[request.page_index]
    evidence = page.findings if request.evidence_type == "text" else page.visual_cues
    if request.evidence_index >= len(evidence):
        raise HTTPException(status_code=422, detail="evidence_index is outside the selected page evidence.")

    record = session.scalar(
        select(ReviewRecord).where(
            ReviewRecord.scan_id == scan_id,
            ReviewRecord.user_id == user.id,
            ReviewRecord.page_index == request.page_index,
            ReviewRecord.evidence_type == request.evidence_type,
            ReviewRecord.evidence_index == request.evidence_index,
        )
    )
    if record is None:
        record = ReviewRecord(scan_id=scan_id, user_id=user.id, **request.model_dump())
        session.add(record)
    else:
        for key, value in request.model_dump().items():
            setattr(record, key, value)
        record.updated_at = utc_now()
    session.flush()
    return _review_response(record)


@router.get("/scans/{scan_id}/reviews", response_model=list[ReviewResponse])
async def list_reviews(
    scan_id: str,
    user: UserPublic = Depends(get_current_user),
    session: Session = Depends(get_database_session),
) -> list[ReviewResponse]:
    try:
        await scan_job_manager.get(scan_id, user.id)
    except ScanJobNotFoundError as error:
        raise HTTPException(status_code=404, detail="Scan job not found.") from error
    records = session.scalars(
        select(ReviewRecord)
        .where(ReviewRecord.scan_id == scan_id, ReviewRecord.user_id == user.id)
        .order_by(ReviewRecord.page_index, ReviewRecord.evidence_type, ReviewRecord.evidence_index)
    ).all()
    return [_review_response(record) for record in records]


@router.post("/scans/run", response_model=ScanResponse, include_in_schema=False)
async def create_scan_synchronously(request: ScanRequest) -> ScanResponse:
    """Compatibility endpoint for trusted local scripts; product clients use authenticated jobs."""
    try:
        return await perform_scan(request)
    except ModelUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except BrowserScanError as error:
        if isinstance(error.__cause__, UnsafeUrlError):
            raise HTTPException(status_code=400, detail=str(error.__cause__)) from error
        raise HTTPException(status_code=502, detail=str(error)) from error
