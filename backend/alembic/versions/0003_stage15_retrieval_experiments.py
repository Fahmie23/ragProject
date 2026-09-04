"""stage 15 controlled retrieval experiment storage

Revision ID: 0003_stage15_experiments
Revises: 0002_stage6_dense_baseline
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0003_stage15_experiments"
down_revision: Union[str, None] = "0002_stage6_dense_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "retrieval_experiments",
        sa.Column("experiment_id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("baseline_profile", sa.String(length=128), nullable=False),
        sa.Column("draft_config", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_retrieval_experiments_baseline_profile",
        "retrieval_experiments",
        ["baseline_profile"],
    )

    op.create_table(
        "retrieval_experiment_runs",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "experiment_id",
            sa.String(length=64),
            sa.ForeignKey("retrieval_experiments.experiment_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.String(length=64),
            sa.ForeignKey("documents.document_id"),
            nullable=False,
        ),
        sa.Column("document_sha256", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("baseline_profile", sa.String(length=128), nullable=False),
        sa.Column("config_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("chunking_version", sa.String(length=64)),
        sa.Column("chunk_artifact_fingerprint", sa.String(length=64)),
        sa.Column("retrieval_trace_version", sa.String(length=64)),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("app_commit_sha", sa.String(length=64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_retrieval_experiment_runs_experiment_id",
        "retrieval_experiment_runs",
        ["experiment_id"],
    )
    op.create_index(
        "ix_retrieval_experiment_runs_document_id",
        "retrieval_experiment_runs",
        ["document_id"],
    )
    op.create_index(
        "ix_retrieval_experiment_runs_status",
        "retrieval_experiment_runs",
        ["status"],
    )

    op.create_table(
        "retrieval_experiment_candidates",
        sa.Column("candidate_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("retrieval_experiment_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        # chunk_id is intentionally not a foreign key to chunks. Live Stage 5
        # replacement deletes/recreates chunk rows, while experiment history
        # must remain reproducible.
        sa.Column("chunk_id", sa.String(length=128), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("semantic_type", sa.String(length=64), nullable=False),
        sa.Column("pages", postgresql.JSONB(), nullable=False),
        sa.Column("section_path", postgresql.JSONB(), nullable=False),
        sa.Column("dense_rank", sa.Integer()),
        sa.Column("dense_score", sa.Float()),
        sa.Column("lexical_rank", sa.Integer()),
        sa.Column("lexical_score", sa.Float()),
        sa.Column("lexical_matched_term_count", sa.Integer()),
        sa.Column("lexical_term_coverage", sa.Float()),
        sa.Column("rrf_rank", sa.Integer()),
        sa.Column("rrf_score", sa.Float()),
        sa.Column("reranker_rank", sa.Integer()),
        sa.Column("reranker_score", sa.Float()),
        sa.Column("final_rank", sa.Integer()),
        sa.Column("selected_top_k", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "run_id",
            "chunk_id",
            name="uq_retrieval_experiment_candidates_run_chunk",
        ),
    )
    op.create_index(
        "ix_retrieval_experiment_candidates_run_id",
        "retrieval_experiment_candidates",
        ["run_id"],
    )
    op.create_index(
        "ix_retrieval_experiment_candidates_run_final_rank",
        "retrieval_experiment_candidates",
        ["run_id", "final_rank"],
    )


def downgrade() -> None:
    op.drop_table("retrieval_experiment_candidates")
    op.drop_table("retrieval_experiment_runs")
    op.drop_table("retrieval_experiments")
