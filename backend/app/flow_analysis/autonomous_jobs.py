from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
import uuid
from urllib.parse import urlparse

from sqlalchemy import delete, select, update

from app.database import (
    AutonomousFindingRecord,
    AutonomousFindingReviewRecord,
    AutonomousFlowRunRecord,
    FlowComparisonRecord,
    FlowGoalRecord,
    FlowGraphEdgeRecord,
    FlowGraphNodeRecord,
    session_scope,
    utc_now,
)
from app.flow_analysis.autonomous_schemas import (
    AutonomousCredentials,
    AutonomousFinding,
    AutonomousFlowJob,
    AutonomousFlowRequest,
    AutonomousFlowRequestSummary,
    AutonomousFlowResult,
)


AUTONOMOUS_PIPELINE_VERSION = "autonomous-flow-and-runtime-v2"


class AutonomousFlowJobNotFoundError(KeyError):
    pass


class AutonomousFlowJobConflictError(RuntimeError):
    pass


def _record_to_job(record: AutonomousFlowRunRecord) -> AutonomousFlowJob:
    return AutonomousFlowJob(
        run_id=record.id,
        status=record.status,
        stage=record.stage,
        progress=record.progress,
        request=AutonomousFlowRequestSummary.model_validate_json(record.request_json),
        created_at=record.created_at,
        updated_at=record.updated_at,
        result=None if record.result_json is None else AutonomousFlowResult.model_validate_json(record.result_json),
        error=record.error,
    )


def _redact_error(error: Exception, request: AutonomousFlowRequest) -> str:
    message = f"{type(error).__name__}: {error}"
    if request.credentials:
        secrets = [request.credentials.username.get_secret_value(), request.credentials.password.get_secret_value()]
        if request.credentials.one_time_code:
            secrets.append(request.credentials.one_time_code.get_secret_value())
        for secret in secrets:
            if secret:
                message = message.replace(secret, "[REDACTED]")
    return message[:4000]


class PersistentAutonomousFlowJobManager:
    """Durable job metadata with secrets retained only in worker memory."""

    def __init__(self, max_concurrent_runs: int = 2) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._ephemeral_requests: dict[str, AutonomousFlowRequest] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent_runs)

    async def create(self, request: AutonomousFlowRequest, user_id: str) -> AutonomousFlowJob:
        run_id = f"auto-{uuid.uuid4().hex[:12]}"
        summary = AutonomousFlowRequestSummary.from_request(request)
        job = await asyncio.to_thread(self._create_record, run_id, summary, user_id)
        self._ephemeral_requests[run_id] = request
        self._schedule(run_id, request)
        return job

    def _schedule(self, run_id: str, request: AutonomousFlowRequest) -> None:
        task = asyncio.create_task(self._execute(run_id, request), name=f"autonomous-flow:{run_id}")
        self._tasks[run_id] = task

        def cleanup(completed: asyncio.Task) -> None:
            # A task cancelled before its coroutine starts never reaches the
            # worker's ``finally`` block. Clear the in-memory request here as a
            # second line of defence so credentials cannot linger.
            if self._tasks.get(run_id) is completed:
                self._tasks.pop(run_id, None)
                self._ephemeral_requests.pop(run_id, None)

        task.add_done_callback(cleanup)

    @staticmethod
    def _create_record(
        run_id: str,
        summary: AutonomousFlowRequestSummary,
        user_id: str,
    ) -> AutonomousFlowJob:
        parsed = urlparse(summary.url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        with session_scope() as session:
            record = AutonomousFlowRunRecord(
                id=run_id,
                user_id=user_id,
                target_url=summary.url,
                target_origin=origin,
                status="queued",
                stage="queued",
                progress=0,
                request_json=summary.model_dump_json(),
                pipeline_version=AUTONOMOUS_PIPELINE_VERSION,
                cancellation_requested=False,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            session.add(record)
            session.flush()
            return _record_to_job(record)

    async def get(self, run_id: str, user_id: str) -> AutonomousFlowJob:
        job = await asyncio.to_thread(self._get_record, run_id, user_id)
        if job is None:
            raise AutonomousFlowJobNotFoundError(run_id)
        return job

    @staticmethod
    def _get_record(run_id: str, user_id: str) -> AutonomousFlowJob | None:
        with session_scope() as session:
            record = session.scalar(
                select(AutonomousFlowRunRecord).where(
                    AutonomousFlowRunRecord.id == run_id,
                    AutonomousFlowRunRecord.user_id == user_id,
                )
            )
            return _record_to_job(record) if record else None

    async def list(self, user_id: str, limit: int = 50) -> list[AutonomousFlowJob]:
        return await asyncio.to_thread(self._list_records, user_id, limit)

    @staticmethod
    def _list_records(user_id: str, limit: int) -> list[AutonomousFlowJob]:
        with session_scope() as session:
            records = session.scalars(
                select(AutonomousFlowRunRecord)
                .where(AutonomousFlowRunRecord.user_id == user_id)
                .order_by(AutonomousFlowRunRecord.created_at.desc())
                .limit(limit)
            ).all()
            return [_record_to_job(record) for record in records]

    @staticmethod
    def _update_record(run_id: str, **changes) -> None:
        with session_scope() as session:
            record = session.get(AutonomousFlowRunRecord, run_id)
            if record is None:
                return
            for key, value in changes.items():
                setattr(record, key, value)
            record.updated_at = utc_now()

    @staticmethod
    def _is_cancelled(run_id: str) -> bool:
        with session_scope() as session:
            value = session.scalar(
                select(AutonomousFlowRunRecord.cancellation_requested).where(AutonomousFlowRunRecord.id == run_id)
            )
            return bool(value)

    @staticmethod
    def _store_result(run_id: str, result: AutonomousFlowResult) -> AutonomousFlowResult:
        with session_scope() as session:
            record = session.get(AutonomousFlowRunRecord, run_id)
            if record is None:
                return result
            session.execute(delete(AutonomousFindingReviewRecord).where(
                AutonomousFindingReviewRecord.finding_id.in_(
                    select(AutonomousFindingRecord.id).where(AutonomousFindingRecord.autonomous_run_id == run_id)
                )
            ))
            session.execute(delete(AutonomousFindingRecord).where(AutonomousFindingRecord.autonomous_run_id == run_id))
            session.execute(delete(FlowGraphEdgeRecord).where(FlowGraphEdgeRecord.autonomous_run_id == run_id))
            session.execute(delete(FlowGraphNodeRecord).where(FlowGraphNodeRecord.autonomous_run_id == run_id))
            session.execute(delete(FlowGoalRecord).where(FlowGoalRecord.autonomous_run_id == run_id))

            persisted_goals = []
            for goal in result.goals:
                goal_findings = []
                all_findings = [goal.overall_finding, *goal.mechanism_findings]
                for finding in all_findings:
                    finding_id = finding.finding_id or str(uuid.uuid4())
                    goal_findings.append(finding.model_copy(update={"finding_id": finding_id}))
                persisted_goal = goal.model_copy(
                    update={
                        "overall_finding": goal_findings[0],
                        "mechanism_findings": goal_findings[1:],
                    }
                )
                persisted_goals.append(persisted_goal)
                session.add(
                    FlowGoalRecord(
                        id=persisted_goal.goal_id,
                        autonomous_run_id=run_id,
                        family=persisted_goal.family,
                        signature=persisted_goal.signature,
                        pairing_confidence=persisted_goal.pairing_confidence,
                        result_json=persisted_goal.model_dump_json(),
                    )
                )
                # These tables intentionally do not expose ORM relationships.
                # Flush the parent row explicitly so PostgreSQL cannot order a
                # finding insert ahead of its flow_goals foreign-key target.
                session.flush()
                for finding in goal_findings:
                    session.add(
                        AutonomousFindingRecord(
                            id=finding.finding_id,
                            autonomous_run_id=run_id,
                            goal_id=persisted_goal.goal_id,
                            category=finding.category,
                            status=finding.status,
                            severity=finding.severity,
                            score=finding.score,
                            confidence=finding.confidence,
                            finding_json=finding.model_dump_json(),
                        )
                    )
            persisted_behavior_findings = []
            for behavior in result.frontend_behavior.findings:
                finding_id = behavior.finding_id or str(uuid.uuid4())
                persisted_behavior = behavior.model_copy(update={"finding_id": finding_id})
                persisted_behavior_findings.append(persisted_behavior)
                summary_finding = AutonomousFinding(
                    finding_id=finding_id,
                    category=behavior.category,
                    status=behavior.status,
                    severity=behavior.severity,
                    score=behavior.score,
                    confidence=behavior.confidence,
                    evidence_refs=[
                        *[f"behavior:{index}" for index, _ in enumerate(behavior.evidence)],
                        *[f"screenshot:{Path(path).name}" for path in behavior.screenshot_paths],
                    ],
                    rationale=behavior.rationale,
                )
                session.add(
                    AutonomousFindingRecord(
                        id=finding_id,
                        autonomous_run_id=run_id,
                        goal_id=None,
                        category=behavior.category,
                        status=behavior.status,
                        severity=behavior.severity,
                        score=behavior.score,
                        confidence=behavior.confidence,
                        finding_json=summary_finding.model_dump_json(),
                    )
                )
            persisted_behavior_report = result.frontend_behavior.model_copy(
                update={"findings": persisted_behavior_findings}
            )
            persisted_result = result.model_copy(
                update={"goals": persisted_goals, "frontend_behavior": persisted_behavior_report}
            )
            for node in persisted_result.graph.nodes:
                session.add(
                    FlowGraphNodeRecord(
                        id=str(uuid.uuid4()),
                        autonomous_run_id=run_id,
                        state_id=node.state_id,
                        fingerprint=node.fingerprint,
                        phase=node.phase,
                        depth=node.depth,
                        url=node.url,
                        observation_json=node.model_dump_json(),
                    )
                )
            for edge in persisted_result.graph.edges:
                session.add(
                    FlowGraphEdgeRecord(
                        id=str(uuid.uuid4()),
                        autonomous_run_id=run_id,
                        edge_id=edge.edge_id,
                        source_state_id=edge.source_state_id,
                        target_state_id=edge.target_state_id,
                        phase=edge.phase,
                        risk=edge.risk,
                        status=edge.status,
                        transition_json=edge.model_dump_json(),
                    )
                )
            status = "needs_input" if persisted_result.summary.requires_assistance else "completed"
            record.status = status
            record.stage = "needs_input" if status == "needs_input" else "completed"
            record.progress = 100
            record.result_json = persisted_result.model_dump_json()
            record.outcome = persisted_result.summary.outcome
            record.confidence = persisted_result.summary.confidence
            record.error = None
            record.updated_at = utc_now()
            session.flush()
            return persisted_result

    async def _execute(self, run_id: str, request: AutonomousFlowRequest) -> None:
        async with self._semaphore:
            await asyncio.to_thread(
                self._update_record,
                run_id,
                status="running",
                stage="validating",
                progress=2,
                result_json=None,
                outcome=None,
                confidence=None,
                error=None,
                cancellation_requested=False,
            )

            async def progress(stage: str, value: int) -> None:
                await asyncio.to_thread(self._update_record, run_id, stage=stage, progress=value)

            async def cancelled() -> bool:
                return await asyncio.to_thread(self._is_cancelled, run_id)

            try:
                from app.flow_analysis.autonomous import perform_autonomous_analysis

                result = await perform_autonomous_analysis(
                    request,
                    run_id=run_id,
                    progress_callback=progress,
                    cancellation_callback=cancelled,
                )
                if await cancelled():
                    await asyncio.to_thread(
                        self._update_record,
                        run_id,
                        status="cancelled",
                        stage="cancelled",
                        error="Autonomous run cancelled.",
                    )
                    return
                await asyncio.to_thread(self._store_result, run_id, result)
            except asyncio.CancelledError:
                await asyncio.to_thread(
                    self._update_record,
                    run_id,
                    status="cancelled",
                    stage="cancelled",
                    error="Autonomous run cancelled.",
                )
            except Exception as error:
                await asyncio.to_thread(
                    self._update_record,
                    run_id,
                    status="failed",
                    stage="failed",
                    error=_redact_error(error, request),
                )
            finally:
                self._ephemeral_requests.pop(run_id, None)

    async def cancel(self, run_id: str, user_id: str) -> AutonomousFlowJob:
        job = await self.get(run_id, user_id)
        if job.status not in {"queued", "running", "needs_input"}:
            raise AutonomousFlowJobConflictError("Only active or input-blocked jobs can be cancelled.")
        await asyncio.to_thread(
            self._update_record,
            run_id,
            cancellation_requested=True,
            status="cancelled",
            stage="cancelled",
            error="Autonomous run cancelled by user.",
        )
        task = self._tasks.get(run_id)
        if task and not task.done():
            task.cancel()
        self._ephemeral_requests.pop(run_id, None)
        return await self.get(run_id, user_id)

    async def provide_credentials(
        self,
        run_id: str,
        user_id: str,
        credentials: AutonomousCredentials,
    ) -> AutonomousFlowJob:
        job = await self.get(run_id, user_id)
        if job.status != "needs_input":
            raise AutonomousFlowJobConflictError("This job is not waiting for credentials or verification input.")
        request = AutonomousFlowRequest(
            url=job.request.url,
            mode=job.request.mode,
            goal_families=job.request.goal_families,
            credentials=credentials,
            allowed_origins=job.request.allowed_origins,
            policy=job.request.policy,
            analyse_models=job.request.analyse_models,
            analyse_behavior=job.request.analyse_behavior,
        )
        safe_summary = AutonomousFlowRequestSummary.from_request(request)
        await asyncio.to_thread(
            self._update_record,
            run_id,
            status="queued",
            stage="queued",
            progress=0,
            request_json=safe_summary.model_dump_json(),
            result_json=None,
            error=None,
            cancellation_requested=False,
        )
        self._ephemeral_requests[run_id] = request
        self._schedule(run_id, request)
        return await self.get(run_id, user_id)


autonomous_flow_job_manager = PersistentAutonomousFlowJobManager()
