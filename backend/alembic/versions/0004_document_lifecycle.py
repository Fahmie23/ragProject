"""document lifecycle cascade cleanup

Revision ID: 0004_document_lifecycle
Revises: 0003_stage15_experiments
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0004_document_lifecycle"
down_revision: Union[str, None] = "0003_stage15_experiments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CONSTRAINT = "retrieval_experiment_runs_document_id_fkey"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "retrieval_experiment_runs", type_="foreignkey")
    op.create_foreign_key(
        _CONSTRAINT,
        "retrieval_experiment_runs",
        "documents",
        ["document_id"],
        ["document_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "retrieval_experiment_runs", type_="foreignkey")
    op.create_foreign_key(
        _CONSTRAINT,
        "retrieval_experiment_runs",
        "documents",
        ["document_id"],
        ["document_id"],
    )
