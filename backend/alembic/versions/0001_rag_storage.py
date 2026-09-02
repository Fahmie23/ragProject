"""initial PostgreSQL and pgvector RAG storage

Revision ID: 0001_rag_storage
Revises:
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql


revision: str = "0001_rag_storage"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "documents",
        sa.Column("document_id", sa.String(length=64), primary_key=True),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("stored_filename", sa.Text(), nullable=False),
        sa.Column("extension", sa.String(length=32), nullable=False),
        sa.Column("detected_mime_type", sa.String(length=255)),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("validation_status", sa.String(length=32), nullable=False),
        sa.Column("validation_errors", postgresql.JSONB(), nullable=False),
        sa.Column("classification", postgresql.JSONB(), nullable=False),
        sa.Column("extraction_status", sa.String(length=32), nullable=False),
        sa.Column("extraction_error", sa.Text()),
        sa.Column("structure_status", sa.String(length=32), nullable=False),
        sa.Column("structure_error", sa.Text()),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True)),
        sa.Column("structured_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_documents_sha256", "documents", ["sha256"])

    op.create_table(
        "chunks",
        sa.Column("chunk_id", sa.String(length=128), primary_key=True),
        sa.Column("document_id", sa.String(length=64), sa.ForeignKey("documents.document_id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("semantic_type", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("context_text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("pages", postgresql.JSONB(), nullable=False),
        sa.Column("section_path", postgresql.JSONB(), nullable=False),
        sa.Column("source_element_ids", postgresql.JSONB(), nullable=False),
        sa.Column("context_element_ids", postgresql.JSONB(), nullable=False),
        sa.Column("refinement_tags", postgresql.JSONB(), nullable=False),
        sa.Column("source_span_ids", postgresql.JSONB(), nullable=False),
        sa.Column("source_block_ids", postgresql.JSONB(), nullable=False),
        sa.Column("source_table_ids", postgresql.JSONB(), nullable=False),
        sa.Column("relationship_ids", postgresql.JSONB(), nullable=False),
        sa.Column("split_part", sa.Integer()),
        sa.Column("split_total", sa.Integer()),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_index"),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_semantic_type", "chunks", ["semantic_type"])
    op.create_index("ix_chunks_document_semantic_type", "chunks", ["document_id", "semantic_type"])

    op.create_table(
        "chunk_embeddings",
        sa.Column("embedding_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("chunk_id", sa.String(length=128), sa.ForeignKey("chunks.chunk_id", ondelete="CASCADE"), nullable=False),
        sa.Column("embedding_model", sa.String(length=255), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("chunk_id", "embedding_model", name="uq_chunk_embeddings_chunk_model"),
    )
    op.create_index("ix_chunk_embeddings_chunk_id", "chunk_embeddings", ["chunk_id"])

    op.create_table(
        "evaluation_questions",
        sa.Column("question_id", sa.String(length=64), primary_key=True),
        sa.Column("document_id", sa.String(length=64), sa.ForeignKey("documents.document_id", ondelete="CASCADE"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("expected_answer", sa.Text()),
        sa.Column("expected_evidence", postgresql.JSONB(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_evaluation_questions_document_id", "evaluation_questions", ["document_id"])
    op.create_index("ix_evaluation_questions_category", "evaluation_questions", ["category"])

    op.create_table(
        "evaluation_runs",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column("document_id", sa.String(length=64), sa.ForeignKey("documents.document_id", ondelete="CASCADE"), nullable=False),
        sa.Column("retrieval_strategy", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=255)),
        sa.Column("reranker_model", sa.String(length=255)),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_evaluation_runs_document_id", "evaluation_runs", ["document_id"])

    op.create_table(
        "evaluation_results",
        sa.Column("result_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=64), sa.ForeignKey("evaluation_runs.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", sa.String(length=64), sa.ForeignKey("evaluation_questions.question_id", ondelete="CASCADE"), nullable=False),
        sa.Column("retrieved_chunk_ids", postgresql.JSONB(), nullable=False),
        sa.Column("answer", sa.Text()),
        sa.Column("citations", postgresql.JSONB(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("run_id", "question_id", name="uq_evaluation_results_run_question"),
    )
    op.create_index("ix_evaluation_results_run_id", "evaluation_results", ["run_id"])
    op.create_index("ix_evaluation_results_question_id", "evaluation_results", ["question_id"])


def downgrade() -> None:
    op.drop_table("evaluation_results")
    op.drop_table("evaluation_runs")
    op.drop_table("evaluation_questions")
    op.drop_table("chunk_embeddings")
    op.drop_table("chunks")
    op.drop_table("documents")
    # Do not drop the vector extension automatically; another schema may use it.
