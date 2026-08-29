from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import delete, select

from app.database import (
    FlowFindingRecord,
    FlowRunRecord,
    FlowStepRecord,
    session_scope,
    utc_now,
)
from app.flow_analysis.engine import perform_flow_analysis
from app.flow_analysis.schemas import FlowJob, FlowPairRequest, FlowPairResult


class FlowJobNotFoundError(KeyError):
    pass


def _record_to_job(record: FlowRunRecord) -> FlowJob:
    return FlowJob(
        run_id=record.id,
        status=record.status,
        request=FlowPairRequest.model_validate_json(record.request_json),
        created_at=record.created_at,
        updated_at=record.updated_at,
        result=None if record.result_json is None else FlowPairResult.model_validate_json(record.result_json),
        error=record.error,
    )


class PersistentFlowJobManager:
    """Durable flow state with bounded in-process execution."""

    def __init__(self, max_concurrent_runs: int = 2) -> None:
        self._tasks: set[asyncio.Task] = set()
        self._semaphore = asyncio.Semaphore(max_concurrent_runs)

    async def create(
        self,
        request: FlowPairRequest,
        user_id: str,
        definition_id: str | None = None,
    ) -> FlowJob:
        run_id = f"flow-{uuid.uuid4().hex[:12]}"
        job = await asyncio.to_thread(self._create_record, run_id, request, user_id, definition_id)
        task = asyncio.create_task(self._execute(run_id, request), name=f"flow:{run_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    @staticmethod
    def _create_record(
        run_id: str,
        request: FlowPairRequest,
        user_id: str,
        definition_id: str | None,
    ) -> FlowJob:
        with session_scope() as session:
            record = FlowRunRecord(
                id=run_id,
                user_id=user_id,
                definition_id=definition_id,
                status="queued",
                request_json=request.model_dump_json(),
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            session.add(record)
            session.flush()
            return _record_to_job(record)

    async def get(self, run_id: str, user_id: str) -> FlowJob:
        job = await asyncio.to_thread(self._get_record, run_id, user_id)
        if job is None:
            raise FlowJobNotFoundError(run_id)
        return job

    @staticmethod
    def _get_record(run_id: str, user_id: str) -> FlowJob | None:
        with session_scope() as session:
            record = session.scalar(
                select(FlowRunRecord).where(FlowRunRecord.id == run_id, FlowRunRecord.user_id == user_id)
            )
            return _record_to_job(record) if record else None

    async def list(self, user_id: str, limit: int = 50) -> list[FlowJob]:
        return await asyncio.to_thread(self._list_records, user_id, limit)

    @staticmethod
    def _list_records(user_id: str, limit: int) -> list[FlowJob]:
        with session_scope() as session:
            records = session.scalars(
                select(FlowRunRecord)
                .where(FlowRunRecord.user_id == user_id)
                .order_by(FlowRunRecord.created_at.desc())
                .limit(limit)
            ).all()
            return [_record_to_job(record) for record in records]

    @staticmethod
    def _update_record(run_id: str, **changes) -> None:
        with session_scope() as session:
            record = session.get(FlowRunRecord, run_id)
            if record is None:
                return
            for key, value in changes.items():
                setattr(record, key, value)
            record.updated_at = utc_now()

    @staticmethod
    def _store_result(run_id: str, result: FlowPairResult) -> None:
        with session_scope() as session:
            record = session.get(FlowRunRecord, run_id)
            if record is None:
                return
            session.execute(delete(FlowStepRecord).where(FlowStepRecord.run_id == run_id))
            session.execute(delete(FlowFindingRecord).where(FlowFindingRecord.run_id == run_id))
            for step in result.acquisition.steps + result.exit.steps:
                session.add(
                    FlowStepRecord(
                        run_id=run_id,
                        phase=step.phase,
                        step_index=step.index,
                        action=step.action,
                        result_json=step.model_dump_json(),
                    )
                )
            session.add(
                FlowFindingRecord(
                    run_id=run_id,
                    category=result.finding.category,
                    severity=result.finding.severity,
                    score=result.finding.score,
                    finding_json=result.finding.model_dump_json(),
                )
            )
            # Persist the evidence rows before exposing a completed status.
            # This also prevents a concurrent poll from observing a completed
            # job whose steps/findings have not been flushed yet.
            session.flush()
            record.status = "completed"
            record.result_json = result.model_dump_json()
            record.error = None
            record.updated_at = utc_now()

    async def _execute(self, run_id: str, request: FlowPairRequest) -> None:
        async with self._semaphore:
            await asyncio.to_thread(self._update_record, run_id, status="running", error=None)
            try:
                result = await perform_flow_analysis(request, run_id)
                await asyncio.to_thread(self._store_result, run_id, result)
            except Exception as error:
                await asyncio.to_thread(
                    self._update_record,
                    run_id,
                    status="failed",
                    error=f"{type(error).__name__}: {error}",
                )
                return


flow_job_manager = PersistentFlowJobManager()
