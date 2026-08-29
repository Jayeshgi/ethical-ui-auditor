import asyncio
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, UserRecord
from app.schemas import ScanRequest, ScanResponse
from app.scans import jobs


@pytest.mark.asyncio
async def test_completed_job_is_persisted_and_owned(monkeypatch) -> None:
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
        user = UserRecord(email="owner@example.com", password_hash="unused")
        other = UserRecord(email="other@example.com", password_hash="unused")
        session.add_all((user, other))
        session.flush()
        user_id, other_id = user.id, other.id

    async def fake_scan(request: ScanRequest) -> ScanResponse:
        return ScanResponse(scan_id="capture-1", status="completed", pages=[], warnings=[])

    monkeypatch.setattr(jobs, "session_scope", test_scope)
    monkeypatch.setattr(jobs, "perform_scan", fake_scan)
    manager = jobs.PersistentScanJobManager()
    created = await manager.create(ScanRequest(url="https://example.com"), user_id)

    for _ in range(30):
        stored = await manager.get(created.scan_id, user_id)
        if stored.status == "completed":
            break
        await asyncio.sleep(0.01)

    assert stored.status == "completed"
    assert stored.result is not None and stored.result.scan_id == "capture-1"
    assert [item.scan_id for item in await manager.list(user_id)] == [created.scan_id]
    with pytest.raises(jobs.ScanJobNotFoundError):
        await manager.get(created.scan_id, other_id)
