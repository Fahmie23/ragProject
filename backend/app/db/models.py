from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DocumentRow(Base):
    __tablename__ = "documents"

    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    stored_filename: Mapped[str] = mapped_column(Text, nullable=False)
    extension: Mapped[str] = mapped_column(String(32), nullable=False)
    detected_mime_type: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    validation_errors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    classification: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    extraction_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_started")
    extraction_error: Mapped[str | None] = mapped_column(Text)
    structure_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_started")
    structure_error: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    structured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    chunks: Mapped[list["ChunkRow"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class ChunkRow(Base):
    __tablename__ = "chunks"

    chunk_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("documents.document_id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    semantic_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    context_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    pages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    section_path: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    source_element_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    context_element_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    refinement_tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    source_span_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    source_block_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    source_table_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    relationship_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    split_part: Mapped[int | None] = mapped_column(Integer)
    split_total: Mapped[int | None] = mapped_column(Integer)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    document: Mapped[DocumentRow] = relationship(back_populates="chunks")
    embeddings: Mapped[list["ChunkEmbeddingRow"]] = relationship(back_populates="chunk", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_index"),
        Index("ix_chunks_document_semantic_type", "document_id", "semantic_type"),
    )


class ChunkEmbeddingRow(Base):
    __tablename__ = "chunk_embeddings"

    embedding_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chunk_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("chunks.chunk_id", ondelete="CASCADE"), nullable=False, index=True
    )
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    # Dimension is intentionally unconstrained here. The embedding model will be
    # selected in the next stage; pgvector supports a variable-dimension column.
    embedding: Mapped[list[float]] = mapped_column(Vector(), nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    chunk: Mapped[ChunkRow] = relationship(back_populates="embeddings")

    __table_args__ = (
        UniqueConstraint("chunk_id", "embedding_model", name="uq_chunk_embeddings_chunk_model"),
        Index("ix_chunk_embeddings_model_dimension", "embedding_model", "dimension"),
    )


class RetrievalExperimentRow(Base):
    __tablename__ = "retrieval_experiments"

    experiment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    baseline_profile: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    draft_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    runs: Mapped[list["RetrievalExperimentRunRow"]] = relationship(
        back_populates="experiment",
        cascade="all, delete-orphan",
    )


class RetrievalExperimentRunRow(Base):
    __tablename__ = "retrieval_experiment_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("retrieval_experiments.experiment_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Retrieval experiment runs are runtime data owned by the uploaded document.
    # Deleting a document cascades its run/candidate history; experiment definitions
    # themselves remain reusable.
    document_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    baseline_profile: Mapped[str] = mapped_column(String(128), nullable=False)
    config_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    chunking_version: Mapped[str | None] = mapped_column(String(64))
    chunk_artifact_fingerprint: Mapped[str | None] = mapped_column(String(64))
    retrieval_trace_version: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    app_commit_sha: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    experiment: Mapped[RetrievalExperimentRow] = relationship(back_populates="runs")
    candidates: Mapped[list["RetrievalExperimentCandidateRow"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class RetrievalExperimentCandidateRow(Base):
    __tablename__ = "retrieval_experiment_candidates"

    candidate_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("retrieval_experiment_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Historical identifier only: intentionally not a foreign key to chunks.
    # Stage 5 chunk replacement deletes/recreates live chunk rows; experiment
    # history must survive that maintenance operation.
    chunk_id: Mapped[str] = mapped_column(String(128), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    semantic_type: Mapped[str] = mapped_column(String(64), nullable=False)
    pages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    section_path: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    dense_rank: Mapped[int | None] = mapped_column(Integer)
    dense_score: Mapped[float | None] = mapped_column(Float)
    lexical_rank: Mapped[int | None] = mapped_column(Integer)
    lexical_score: Mapped[float | None] = mapped_column(Float)
    lexical_matched_term_count: Mapped[int | None] = mapped_column(Integer)
    lexical_term_coverage: Mapped[float | None] = mapped_column(Float)
    rrf_rank: Mapped[int | None] = mapped_column(Integer)
    rrf_score: Mapped[float | None] = mapped_column(Float)
    reranker_rank: Mapped[int | None] = mapped_column(Integer)
    reranker_score: Mapped[float | None] = mapped_column(Float)
    final_rank: Mapped[int | None] = mapped_column(Integer)
    selected_top_k: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    run: Mapped[RetrievalExperimentRunRow] = relationship(back_populates="candidates")

    __table_args__ = (
        UniqueConstraint("run_id", "chunk_id", name="uq_retrieval_experiment_candidates_run_chunk"),
        Index("ix_retrieval_experiment_candidates_run_final_rank", "run_id", "final_rank"),
    )


class EvaluationQuestionRow(Base):
    __tablename__ = "evaluation_questions"

    question_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("documents.document_id", ondelete="CASCADE"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    expected_answer: Mapped[str | None] = mapped_column(Text)
    expected_evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class EvaluationRunRow(Base):
    __tablename__ = "evaluation_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("documents.document_id", ondelete="CASCADE"), nullable=False, index=True
    )
    retrieval_strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str | None] = mapped_column(String(255))
    reranker_model: Mapped[str | None] = mapped_column(String(255))
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvaluationResultRow(Base):
    __tablename__ = "evaluation_results"

    result_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("evaluation_runs.run_id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("evaluation_questions.question_id", ondelete="CASCADE"), nullable=False, index=True
    )
    retrieved_chunk_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    answer: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "question_id", name="uq_evaluation_results_run_question"),
    )
