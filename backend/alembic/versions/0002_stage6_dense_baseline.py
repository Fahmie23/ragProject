"""stage 6 dense retrieval baseline support

Revision ID: 0002_stage6_dense_baseline
Revises: 0001_rag_storage
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0002_stage6_dense_baseline"
down_revision: Union[str, None] = "0001_rag_storage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Exact cosine search is the Stage 6 baseline. This B-tree only accelerates
    # model/dimension filtering; HNSW/IVFFlat is intentionally deferred until
    # retrieval quality is measured and a fixed embedding dimension is chosen.
    op.create_index(
        "ix_chunk_embeddings_model_dimension",
        "chunk_embeddings",
        ["embedding_model", "dimension"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_chunk_embeddings_model_dimension", table_name="chunk_embeddings")
