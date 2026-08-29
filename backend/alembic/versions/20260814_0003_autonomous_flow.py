"""Add autonomous exploration, graph, multi-finding and comparison storage.

Revision ID: 20260814_0003
Revises: 20260814_0002
"""

from alembic import op
import sqlalchemy as sa


revision = "20260814_0003"
down_revision = "20260814_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "autonomous_flow_runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("target_url", sa.String(length=2000), nullable=False),
        sa.Column("target_origin", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("pipeline_version", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("cancellation_requested", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns, unique in (
        ("ix_autonomous_flow_runs_user_id", ["user_id"], False),
        ("ix_autonomous_flow_runs_target_origin", ["target_origin"], False),
        ("ix_autonomous_flow_runs_status", ["status"], False),
        ("ix_autonomous_flow_runs_stage", ["stage"], False),
        ("ix_autonomous_flow_runs_outcome", ["outcome"], False),
        ("ix_autonomous_flow_runs_created_at", ["created_at"], False),
        ("ix_autonomous_flow_runs_user_created", ["user_id", "created_at"], False),
        ("ix_autonomous_flow_runs_origin_created", ["target_origin", "created_at"], False),
    ):
        op.create_index(name, "autonomous_flow_runs", columns, unique=unique)

    op.create_table(
        "flow_goals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("autonomous_run_id", sa.String(length=32), nullable=False),
        sa.Column("family", sa.String(length=64), nullable=False),
        sa.Column("signature", sa.String(length=200), nullable=False),
        sa.Column("pairing_confidence", sa.Float(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["autonomous_run_id"], ["autonomous_flow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("autonomous_run_id", "signature", name="uq_autonomous_goal_signature"),
    )
    op.create_index("ix_flow_goals_autonomous_run_id", "flow_goals", ["autonomous_run_id"])
    op.create_index("ix_flow_goals_family", "flow_goals", ["family"])
    op.create_index("ix_flow_goals_signature", "flow_goals", ["signature"])

    op.create_table(
        "flow_graph_nodes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("autonomous_run_id", sa.String(length=32), nullable=False),
        sa.Column("state_id", sa.String(length=64), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("phase", sa.String(length=16), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("observation_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["autonomous_run_id"], ["autonomous_flow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("autonomous_run_id", "state_id", name="uq_autonomous_graph_state"),
    )
    op.create_index("ix_flow_graph_nodes_autonomous_run_id", "flow_graph_nodes", ["autonomous_run_id"])
    op.create_index("ix_flow_graph_nodes_fingerprint", "flow_graph_nodes", ["fingerprint"])
    op.create_index("ix_flow_graph_nodes_phase", "flow_graph_nodes", ["phase"])

    op.create_table(
        "flow_graph_edges",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("autonomous_run_id", sa.String(length=32), nullable=False),
        sa.Column("edge_id", sa.String(length=64), nullable=False),
        sa.Column("source_state_id", sa.String(length=64), nullable=False),
        sa.Column("target_state_id", sa.String(length=64), nullable=True),
        sa.Column("phase", sa.String(length=16), nullable=False),
        sa.Column("risk", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("transition_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["autonomous_run_id"], ["autonomous_flow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("autonomous_run_id", "edge_id", name="uq_autonomous_graph_edge"),
    )
    for name, columns in (
        ("ix_flow_graph_edges_autonomous_run_id", ["autonomous_run_id"]),
        ("ix_flow_graph_edges_source_state_id", ["source_state_id"]),
        ("ix_flow_graph_edges_target_state_id", ["target_state_id"]),
        ("ix_flow_graph_edges_phase", ["phase"]),
        ("ix_flow_graph_edges_risk", ["risk"]),
        ("ix_flow_graph_edges_status", ["status"]),
    ):
        op.create_index(name, "flow_graph_edges", columns)

    op.create_table(
        "autonomous_flow_findings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("autonomous_run_id", sa.String(length=32), nullable=False),
        sa.Column("goal_id", sa.String(length=36), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("finding_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["autonomous_run_id"], ["autonomous_flow_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["goal_id"], ["flow_goals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in (
        ("ix_autonomous_flow_findings_autonomous_run_id", ["autonomous_run_id"]),
        ("ix_autonomous_flow_findings_goal_id", ["goal_id"]),
        ("ix_autonomous_flow_findings_category", ["category"]),
        ("ix_autonomous_flow_findings_status", ["status"]),
        ("ix_autonomous_flow_findings_severity", ["severity"]),
    ):
        op.create_index(name, "autonomous_flow_findings", columns)

    op.create_table(
        "autonomous_finding_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("finding_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["finding_id"], ["autonomous_flow_findings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("finding_id", "user_id", name="uq_autonomous_finding_reviewer"),
    )
    op.create_index("ix_autonomous_finding_reviews_finding_id", "autonomous_finding_reviews", ["finding_id"])
    op.create_index("ix_autonomous_finding_reviews_user_id", "autonomous_finding_reviews", ["user_id"])

    op.create_table(
        "flow_comparisons",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("baseline_run_id", sa.String(length=32), nullable=False),
        sa.Column("candidate_run_id", sa.String(length=32), nullable=False),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["baseline_run_id"], ["autonomous_flow_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_run_id"], ["autonomous_flow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "baseline_run_id", "candidate_run_id", name="uq_flow_comparison_pair"),
    )
    for name, columns in (
        ("ix_flow_comparisons_user_id", ["user_id"]),
        ("ix_flow_comparisons_baseline_run_id", ["baseline_run_id"]),
        ("ix_flow_comparisons_candidate_run_id", ["candidate_run_id"]),
        ("ix_flow_comparisons_verdict", ["verdict"]),
        ("ix_flow_comparisons_created_at", ["created_at"]),
    ):
        op.create_index(name, "flow_comparisons", columns)


def downgrade() -> None:
    op.drop_table("flow_comparisons")
    op.drop_table("autonomous_finding_reviews")
    op.drop_table("autonomous_flow_findings")
    op.drop_table("flow_graph_edges")
    op.drop_table("flow_graph_nodes")
    op.drop_table("flow_goals")
    op.drop_table("autonomous_flow_runs")
