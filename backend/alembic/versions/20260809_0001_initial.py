"""Create users, scan jobs, and finding reviews.

Revision ID: 20260809_0001
Revises:
"""

from alembic import op
import sqlalchemy as sa


revision = "20260809_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table(
        "scan_jobs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scan_jobs_status", "scan_jobs", ["status"], unique=False)
    op.create_index("ix_scan_jobs_user_id", "scan_jobs", ["user_id"], unique=False)
    op.create_index("ix_scan_jobs_created_at", "scan_jobs", ["created_at"], unique=False)
    op.create_index("ix_scan_jobs_user_created", "scan_jobs", ["user_id", "created_at"], unique=False)
    op.create_table(
        "finding_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scan_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("evidence_type", sa.String(length=16), nullable=False),
        sa.Column("evidence_index", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["scan_id"], ["scan_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scan_id", "user_id", "page_index", "evidence_type", "evidence_index", name="uq_review_target"),
    )
    op.create_index("ix_finding_reviews_scan_id", "finding_reviews", ["scan_id"], unique=False)
    op.create_index("ix_finding_reviews_user_id", "finding_reviews", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_table("finding_reviews")
    op.drop_table("scan_jobs")
    op.drop_table("users")
