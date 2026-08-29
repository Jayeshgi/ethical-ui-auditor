from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import routes
from app.database import Base, ScanRecord, UserRecord
from app.schemas import (
    BoundingBox,
    Finding,
    PageResult,
    ReviewRequest,
    ScanJob,
    ScanRequest,
    ScanResponse,
    UserPublic,
    VisualCue,
)


def completed_job(scan_id: str, category: str = "false_urgency", cue: str = "COUNTDOWN TIMER") -> ScanJob:
    page = PageResult(
        url="https://example.com",
        title="Example",
        screenshot_path="runtime_data/example.png",
        text_blocks=[],
        findings=[
            Finding(
                category=category,
                model_confidence=0.8,
                threshold=0.5,
                model_version="bert-test",
                phrase="Ends soon",
                source="dom",
                bounding_box=BoundingBox(x=0, y=0, width=10, height=10),
            )
        ],
        visual_cues=[
            VisualCue(
                cue=cue,
                model_confidence=0.7,
                threshold=0.25,
                model_version="yolo-test",
                bounding_box=BoundingBox(x=0, y=0, width=10, height=10),
            )
        ],
    )
    result = ScanResponse(scan_id=f"capture-{scan_id}", status="completed", pages=[page])
    now = datetime.now(UTC)
    return ScanJob(
        scan_id=scan_id,
        status="completed",
        request=ScanRequest(url="https://example.com"),
        created_at=now,
        updated_at=now,
        result=result,
    )


@pytest.mark.asyncio
async def test_reviewer_decision_is_created_and_updated(monkeypatch) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    user_id = "user-1"
    scan_id = "job-1"
    with Session(engine) as setup:
        setup.add(UserRecord(id=user_id, email="reviewer@example.com", password_hash="unused"))
        setup.add(
            ScanRecord(
                id=scan_id,
                user_id=user_id,
                status="completed",
                request_json=ScanRequest(url="https://example.com").model_dump_json(),
                result_json=completed_job(scan_id).result.model_dump_json(),
            )
        )
        setup.commit()

    class FakeManager:
        async def get(self, requested_scan_id: str, requested_user_id: str):
            assert requested_scan_id == scan_id and requested_user_id == user_id
            return completed_job(scan_id)

    monkeypatch.setattr(routes, "scan_job_manager", FakeManager())
    user = UserPublic(id=user_id, email="reviewer@example.com", role="reviewer", created_at=datetime.now(UTC))
    with Session(engine) as session:
        created = await routes.upsert_review(
            scan_id,
            ReviewRequest(page_index=0, evidence_type="text", evidence_index=0, decision="confirmed", severity="high"),
            user,
            session,
        )
        session.commit()
        updated = await routes.upsert_review(
            scan_id,
            ReviewRequest(page_index=0, evidence_type="text", evidence_index=0, decision="rejected", severity="low", notes="Benign context"),
            user,
            session,
        )
        session.commit()
        reviews = await routes.list_reviews(scan_id, user, session)

    assert created.id == updated.id
    assert updated.decision == "rejected"
    assert updated.notes == "Benign context"
    assert len(reviews) == 1


@pytest.mark.asyncio
async def test_scan_comparison_returns_category_deltas(monkeypatch) -> None:
    left = completed_job("left", "false_urgency", "COUNTDOWN TIMER")
    right = completed_job("right", "false_scarcity", "LOW STOCK MESSAGE")

    class FakeManager:
        async def get(self, scan_id: str, user_id: str):
            return {"left": left, "right": right}[scan_id]

    monkeypatch.setattr(routes, "scan_job_manager", FakeManager())
    user = UserPublic(id="user-1", email="reviewer@example.com", role="reviewer", created_at=datetime.now(UTC))
    comparison = await routes.compare_scans("left", "right", user)

    assert comparison.text_category_delta == {"false_scarcity": 1, "false_urgency": -1}
    assert comparison.visual_cue_delta == {"COUNTDOWN TIMER": -1, "LOW STOCK MESSAGE": 1}
