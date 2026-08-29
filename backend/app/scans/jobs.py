from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import uuid

from sqlalchemy import select

from app.database import ScanRecord, session_scope, utc_now
from app.schemas import ScanJob, ScanRequest, ScanResponse
from app.scans.service import perform_scan


class ScanJobNotFoundError(KeyError):
    pass


class InMemoryScanJobManager:
    """Non-blocking job lifecycle; durable storage replaces this in the next milestone."""

    def __init__(self) -> None:
        self._jobs: dict[str, ScanJob] = {}
        self._tasks: set[asyncio.Task] = set()
        self._lock = asyncio.Lock()

    async def create(self, request: ScanRequest) -> ScanJob:
        now = datetime.now(UTC)
        job = ScanJob(
            scan_id=f"job-{uuid.uuid4().hex[:12]}",
            status="queued",
            request=request,
            created_at=now,
            updated_at=now,
        )
        async with self._lock:
            self._jobs[job.scan_id] = job
        task = asyncio.create_task(self._execute(job.scan_id, request), name=f"scan:{job.scan_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def get(self, scan_id: str) -> ScanJob:
        async with self._lock:
            job = self._jobs.get(scan_id)
            if job is None:
                raise ScanJobNotFoundError(scan_id)
            return job.model_copy(deep=True)

    async def _update(self, scan_id: str, **changes) -> None:
        async with self._lock:
            current = self._jobs[scan_id]
            self._jobs[scan_id] = current.model_copy(update={**changes, "updated_at": datetime.now(UTC)})

    async def _execute(self, scan_id: str, request: ScanRequest) -> None:
        await self._update(scan_id, status="running")
        try:
            result = await perform_scan(request)
        except Exception as error:
            await self._update(scan_id, status="failed", error=f"{type(error).__name__}: {error}")
            return
        await self._update(scan_id, status="completed", result=result)


def _record_to_job(record: ScanRecord) -> ScanJob:
    return ScanJob(
        scan_id=record.id,
        status=record.status,
        request=ScanRequest.model_validate_json(record.request_json),
        created_at=record.created_at,
        updated_at=record.updated_at,
        result=None if record.result_json is None else ScanResponse.model_validate_json(record.result_json),
        error=record.error,
    )


class PersistentScanJobManager:
    """Durable job state with in-process execution; a queue worker can replace execution later."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task] = set()

    async def create(self, request: ScanRequest, user_id: str) -> ScanJob:
        scan_id = f"job-{uuid.uuid4().hex[:12]}"
        job = await asyncio.to_thread(self._create_record, scan_id, request, user_id)
        task = asyncio.create_task(self._execute(scan_id, request), name=f"scan:{scan_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    @staticmethod
    def _create_record(scan_id: str, request: ScanRequest, user_id: str) -> ScanJob:
        with session_scope() as session:
            record = ScanRecord(
                id=scan_id,
                user_id=user_id,
                status="queued",
                request_json=request.model_dump_json(),
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            session.add(record)
            session.flush()
            return _record_to_job(record)

    async def get(self, scan_id: str, user_id: str) -> ScanJob:
        job = await asyncio.to_thread(self._get_record, scan_id, user_id)
        if job is None:
            raise ScanJobNotFoundError(scan_id)
        return job

    @staticmethod
    def _get_record(scan_id: str, user_id: str) -> ScanJob | None:
        with session_scope() as session:
            record = session.scalar(select(ScanRecord).where(ScanRecord.id == scan_id, ScanRecord.user_id == user_id))
            return _record_to_job(record) if record else None

    async def list(self, user_id: str, limit: int = 50) -> list[ScanJob]:
        return await asyncio.to_thread(self._list_records, user_id, limit)

    @staticmethod
    def _list_records(user_id: str, limit: int) -> list[ScanJob]:
        with session_scope() as session:
            records = session.scalars(
                select(ScanRecord).where(ScanRecord.user_id == user_id).order_by(ScanRecord.created_at.desc()).limit(limit)
            ).all()
            return [_record_to_job(record) for record in records]

    @staticmethod
    def _update_record(scan_id: str, **changes) -> None:
        with session_scope() as session:
            record = session.get(ScanRecord, scan_id)
            if record is None:
                return
            for key, value in changes.items():
                setattr(record, key, value)
            record.updated_at = utc_now()

    async def _execute(self, scan_id: str, request: ScanRequest) -> None:
        await asyncio.to_thread(self._update_record, scan_id, status="running", error=None)
        try:
            result = await perform_scan(request)
        except Exception as error:
            await asyncio.to_thread(self._update_record, scan_id, status="failed", error=f"{type(error).__name__}: {error}")
            return
        await asyncio.to_thread(
            self._update_record,
            scan_id,
            status="completed",
            result_json=result.model_dump_json(),
            error=None,
        )


scan_job_manager = PersistentScanJobManager()
