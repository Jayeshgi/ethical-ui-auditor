from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import uuid

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, create_engine, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import DATABASE_URL, RUNTIME_DATA_DIR


class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC)


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(32), default="reviewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ScanRecord(Base):
    __tablename__ = "scan_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    request_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __table_args__ = (Index("ix_scan_jobs_user_created", "user_id", "created_at"),)


class ReviewRecord(Base):
    __tablename__ = "finding_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    scan_id: Mapped[str] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    page_index: Mapped[int] = mapped_column(Integer)
    evidence_type: Mapped[str] = mapped_column(String(16))
    evidence_index: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __table_args__ = (
        UniqueConstraint("scan_id", "user_id", "page_index", "evidence_type", "evidence_index", name="uq_review_target"),
    )


class FlowDefinitionRecord(Base):
    __tablename__ = "flow_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    definition_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class FlowRunRecord(Base):
    __tablename__ = "flow_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    definition_id: Mapped[str | None] = mapped_column(
        ForeignKey("flow_definitions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), index=True)
    request_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __table_args__ = (Index("ix_flow_runs_user_created", "user_id", "created_at"),)


class FlowStepRecord(Base):
    __tablename__ = "flow_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("flow_runs.id", ondelete="CASCADE"), index=True)
    phase: Mapped[str] = mapped_column(String(16))
    step_index: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(32))
    result_json: Mapped[str] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("run_id", "phase", "step_index", name="uq_flow_step_position"),)


class FlowFindingRecord(Base):
    __tablename__ = "flow_findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("flow_runs.id", ondelete="CASCADE"), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    score: Mapped[float] = mapped_column(Float)
    finding_json: Mapped[str] = mapped_column(Text)


class FlowReviewRecord(Base):
    __tablename__ = "flow_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("flow_runs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    decision: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __table_args__ = (UniqueConstraint("run_id", "user_id", name="uq_flow_review_reviewer"),)


class AutonomousFlowRunRecord(Base):
    __tablename__ = "autonomous_flow_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    target_url: Mapped[str] = mapped_column(String(2000))
    target_origin: Mapped[str] = mapped_column(String(512), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    stage: Mapped[str] = mapped_column(String(64), index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    request_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    pipeline_version: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index("ix_autonomous_flow_runs_user_created", "user_id", "created_at"),
        Index("ix_autonomous_flow_runs_origin_created", "target_origin", "created_at"),
    )


class FlowGoalRecord(Base):
    __tablename__ = "flow_goals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    autonomous_run_id: Mapped[str] = mapped_column(
        ForeignKey("autonomous_flow_runs.id", ondelete="CASCADE"), index=True
    )
    family: Mapped[str] = mapped_column(String(64), index=True)
    signature: Mapped[str] = mapped_column(String(200), index=True)
    pairing_confidence: Mapped[float] = mapped_column(Float)
    result_json: Mapped[str] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("autonomous_run_id", "signature", name="uq_autonomous_goal_signature"),)


class FlowGraphNodeRecord(Base):
    __tablename__ = "flow_graph_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    autonomous_run_id: Mapped[str] = mapped_column(
        ForeignKey("autonomous_flow_runs.id", ondelete="CASCADE"), index=True
    )
    state_id: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    phase: Mapped[str] = mapped_column(String(16), index=True)
    depth: Mapped[int] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(String(2000))
    observation_json: Mapped[str] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("autonomous_run_id", "state_id", name="uq_autonomous_graph_state"),)


class FlowGraphEdgeRecord(Base):
    __tablename__ = "flow_graph_edges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    autonomous_run_id: Mapped[str] = mapped_column(
        ForeignKey("autonomous_flow_runs.id", ondelete="CASCADE"), index=True
    )
    edge_id: Mapped[str] = mapped_column(String(64))
    source_state_id: Mapped[str] = mapped_column(String(64), index=True)
    target_state_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    phase: Mapped[str] = mapped_column(String(16), index=True)
    risk: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    transition_json: Mapped[str] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("autonomous_run_id", "edge_id", name="uq_autonomous_graph_edge"),)


class AutonomousFindingRecord(Base):
    __tablename__ = "autonomous_flow_findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    autonomous_run_id: Mapped[str] = mapped_column(
        ForeignKey("autonomous_flow_runs.id", ondelete="CASCADE"), index=True
    )
    goal_id: Mapped[str | None] = mapped_column(ForeignKey("flow_goals.id", ondelete="CASCADE"), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    finding_json: Mapped[str] = mapped_column(Text)


class AutonomousFindingReviewRecord(Base):
    __tablename__ = "autonomous_finding_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    finding_id: Mapped[str] = mapped_column(
        ForeignKey("autonomous_flow_findings.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    decision: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __table_args__ = (UniqueConstraint("finding_id", "user_id", name="uq_autonomous_finding_reviewer"),)


class FlowComparisonRecord(Base):
    __tablename__ = "flow_comparisons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    baseline_run_id: Mapped[str] = mapped_column(
        ForeignKey("autonomous_flow_runs.id", ondelete="CASCADE"), index=True
    )
    candidate_run_id: Mapped[str] = mapped_column(
        ForeignKey("autonomous_flow_runs.id", ondelete="CASCADE"), index=True
    )
    verdict: Mapped[str] = mapped_column(String(32), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    __table_args__ = (
        UniqueConstraint("user_id", "baseline_run_id", "candidate_run_id", name="uq_flow_comparison_pair"),
    )


connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def initialize_database() -> None:
    RUNTIME_DATA_DIR.mkdir(parents=True, exist_ok=True)
    # SQLite is the intentionally self-contained test/development fallback.
    # PostgreSQL schema changes must go through Alembic so a service start
    # cannot silently create only part of a newer schema and bypass revision
    # history.
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)
    with SessionLocal.begin() as session:
        session.execute(
            update(ScanRecord)
            .where(ScanRecord.status.in_(("queued", "running")))
            .values(status="failed", error="Application restarted before the scan completed.", updated_at=utc_now())
        )
        session.execute(
            update(FlowRunRecord)
            .where(FlowRunRecord.status.in_(("queued", "running")))
            .values(status="failed", error="Application restarted before the flow completed.", updated_at=utc_now())
        )
        session.execute(
            update(AutonomousFlowRunRecord)
            .where(AutonomousFlowRunRecord.status.in_(("queued", "running")))
            .values(
                status="failed",
                stage="failed",
                error="Application restarted before the autonomous flow completed.",
                updated_at=utc_now(),
            )
        )


@contextmanager
def session_scope():
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_database_session():
    with session_scope() as session:
        yield session
