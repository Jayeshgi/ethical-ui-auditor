"""Add paired flow definitions, runs, evidence, findings, and reviews.

Revision ID: 20260814_0002
Revises: 20260809_0001
"""

from alembic import op
import sqlalchemy as sa


revision = "20260814_0002"
down_revision = "20260809_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flow_definitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("definition_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_flow_definitions_user_id", "flow_definitions", ["user_id"])
    op.create_index("ix_flow_definitions_name", "flow_definitions", ["name"])

    op.create_table(
        "flow_runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("definition_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["definition_id"], ["flow_definitions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_flow_runs_user_id", "flow_runs", ["user_id"])
    op.create_index("ix_flow_runs_definition_id", "flow_runs", ["definition_id"])
    op.create_index("ix_flow_runs_status", "flow_runs", ["status"])
    op.create_index("ix_flow_runs_created_at", "flow_runs", ["created_at"])
    op.create_index("ix_flow_runs_user_created", "flow_runs", ["user_id", "created_at"])

    op.create_table(
        "flow_steps",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("phase", sa.String(length=16), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["flow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "phase", "step_index", name="uq_flow_step_position"),
    )
    op.create_index("ix_flow_steps_run_id", "flow_steps", ["run_id"])

    op.create_table(
        "flow_findings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("finding_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["flow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_flow_findings_run_id", "flow_findings", ["run_id"], unique=True)
    op.create_index("ix_flow_findings_category", "flow_findings", ["category"])
    op.create_index("ix_flow_findings_severity", "flow_findings", ["severity"])

    op.create_table(
        "flow_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["flow_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "user_id", name="uq_flow_review_reviewer"),
    )
    op.create_index("ix_flow_reviews_run_id", "flow_reviews", ["run_id"])
    op.create_index("ix_flow_reviews_user_id", "flow_reviews", ["user_id"])


def downgrade() -> None:
    op.drop_table("flow_reviews")
    op.drop_table("flow_findings")
    op.drop_table("flow_steps")
    op.drop_table("flow_runs")
    op.drop_table("flow_definitions")
