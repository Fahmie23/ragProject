from __future__ import annotations

from sqlalchemy import case, delete, func, select

from app.db.models import ChunkEmbeddingRow, ChunkRow, DocumentRow
from app.db.session import session_scope
from app.schemas import ChunkingArtifact, DocumentRecord
from app.services.lexical import LexicalQueryPlan, build_lexical_query_plan


def upsert_document(record: DocumentRecord) -> None:
    values = {
        "original_filename": record.original_filename,
        "stored_filename": record.stored_filename,
        "extension": record.extension,
        "detected_mime_type": record.detected_mime_type,
        "size_bytes": record.size_bytes,
        "sha256": record.sha256,
        "validation_status": record.validation_status,
        "validation_errors": list(record.validation_errors),
        "classification": record.classification.model_dump(mode="json"),
        "extraction_status": record.extraction_status,
        "extraction_error": record.extraction_error,
        "structure_status": record.structure_status,
        "structure_error": record.structure_error,
        "ingested_at": record.ingested_at,
        "extracted_at": record.extracted_at,
        "structured_at": record.structured_at,
    }
    with session_scope() as session:
        row = session.get(DocumentRow, record.document_id)
        if row is None:
            row = DocumentRow(document_id=record.document_id, **values)
            session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)


def replace_chunks(record: DocumentRecord, artifact: ChunkingArtifact) -> None:
    """Persist the latest Stage 5 chunk artifact transactionally.

    JSON remains the deterministic artifact/source of truth. PostgreSQL stores
    queryable chunk text and metadata for indexing, retrieval and evaluation.
    Replacing chunks intentionally cascades any stale embeddings.
    """

    upsert_document(record)
    with session_scope() as session:
        session.execute(delete(ChunkRow).where(ChunkRow.document_id == artifact.document_id))
        session.add_all(
            [
                ChunkRow(
                    chunk_id=chunk.chunk_id,
                    document_id=artifact.document_id,
                    chunk_index=chunk.chunk_index,
                    semantic_type=chunk.semantic_type,
                    text=chunk.text,
                    content_text=chunk.content_text,
                    context_text=chunk.context_text,
                    token_count=chunk.token_count,
                    pages=list(chunk.pages),
                    section_path=list(chunk.section_path),
                    source_element_ids=list(chunk.source_element_ids),
                    context_element_ids=list(chunk.context_element_ids),
                    refinement_tags=list(chunk.refinement_tags),
                    source_span_ids=list(chunk.source_span_ids),
                    source_block_ids=list(chunk.source_block_ids),
                    source_table_ids=list(chunk.source_table_ids),
                    relationship_ids=list(chunk.relationship_ids),
                    split_part=chunk.split_part,
                    split_total=chunk.split_total,
                    generated_at=artifact.generated_at,
                )
                for chunk in artifact.chunks
            ]
        )


def delete_chunks(document_id: str) -> None:
    with session_scope() as session:
        session.execute(delete(ChunkRow).where(ChunkRow.document_id == document_id))



def document_chunk_ids(document_id: str) -> set[str]:
    with session_scope() as session:
        return set(session.scalars(select(ChunkRow.chunk_id).where(ChunkRow.document_id == document_id)).all())


def chunks_for_embedding(document_id: str, embedding_model: str, *, force: bool = False) -> list[dict[str, object]]:
    """Return retrieval-ready chunk text that still needs this model's embedding."""

    with session_scope() as session:
        statement = (
            select(ChunkRow)
            .where(ChunkRow.document_id == document_id)
            .order_by(ChunkRow.chunk_index)
        )
        if not force:
            statement = statement.where(
                ~ChunkRow.embeddings.any(ChunkEmbeddingRow.embedding_model == embedding_model)
            )
        rows = session.scalars(statement).all()
        return [
            {
                "chunk_id": row.chunk_id,
                "chunk_index": row.chunk_index,
                "text": row.text,
            }
            for row in rows
        ]


def delete_embeddings(document_id: str, embedding_model: str | None = None) -> int:
    with session_scope() as session:
        chunk_ids = select(ChunkRow.chunk_id).where(ChunkRow.document_id == document_id)
        statement = delete(ChunkEmbeddingRow).where(ChunkEmbeddingRow.chunk_id.in_(chunk_ids))
        if embedding_model:
            statement = statement.where(ChunkEmbeddingRow.embedding_model == embedding_model)
        result = session.execute(statement)
        return int(result.rowcount or 0)


def store_embeddings(
    *,
    embedding_model: str,
    chunk_vectors: list[tuple[str, list[float], dict[str, object]]],
) -> int:
    if not chunk_vectors:
        return 0
    dimensions = {len(vector) for _, vector, _ in chunk_vectors}
    if len(dimensions) != 1 or next(iter(dimensions)) <= 0:
        raise ValueError("All stored embeddings in one batch must share a positive dimension.")
    dimension = next(iter(dimensions))
    with session_scope() as session:
        session.add_all(
            [
                ChunkEmbeddingRow(
                    chunk_id=chunk_id,
                    embedding_model=embedding_model,
                    dimension=dimension,
                    embedding=vector,
                    metadata_json=metadata,
                )
                for chunk_id, vector, metadata in chunk_vectors
            ]
        )
    return len(chunk_vectors)


def embedding_status(document_id: str, embedding_model: str) -> dict[str, int | bool | None | str]:
    with session_scope() as session:
        chunk_count = int(
            session.scalar(select(func.count()).select_from(ChunkRow).where(ChunkRow.document_id == document_id)) or 0
        )
        embedded_count = int(
            session.scalar(
                select(func.count())
                .select_from(ChunkEmbeddingRow)
                .join(ChunkRow, ChunkRow.chunk_id == ChunkEmbeddingRow.chunk_id)
                .where(
                    ChunkRow.document_id == document_id,
                    ChunkEmbeddingRow.embedding_model == embedding_model,
                )
            )
            or 0
        )
        dimensions = session.scalars(
            select(ChunkEmbeddingRow.dimension)
            .join(ChunkRow, ChunkRow.chunk_id == ChunkEmbeddingRow.chunk_id)
            .where(
                ChunkRow.document_id == document_id,
                ChunkEmbeddingRow.embedding_model == embedding_model,
            )
            .distinct()
        ).all()
    dimension = dimensions[0] if len(dimensions) == 1 else None
    return {
        "document_id": document_id,
        "embedding_model": embedding_model,
        "chunk_count": chunk_count,
        "embedded_chunk_count": embedded_count,
        "missing_chunk_count": max(0, chunk_count - embedded_count),
        "dimension": dimension,
        "complete": chunk_count > 0 and embedded_count == chunk_count and len(dimensions) == 1,
    }


def dense_search(
    *,
    document_id: str,
    embedding_model: str,
    query_vector: list[float],
    top_k: int,
    semantic_types: list[str] | None = None,
) -> list[dict[str, object]]:
    """Exact cosine search in pgvector; ANN indexing is intentionally deferred."""

    if not query_vector:
        raise ValueError("Query embedding cannot be empty.")
    dimension = len(query_vector)
    distance = ChunkEmbeddingRow.embedding.cosine_distance(query_vector).label("distance")
    statement = (
        select(ChunkRow, distance)
        .join(ChunkEmbeddingRow, ChunkEmbeddingRow.chunk_id == ChunkRow.chunk_id)
        .where(
            ChunkRow.document_id == document_id,
            ChunkEmbeddingRow.embedding_model == embedding_model,
            ChunkEmbeddingRow.dimension == dimension,
        )
    )
    if semantic_types:
        statement = statement.where(ChunkRow.semantic_type.in_(semantic_types))
    statement = statement.order_by(distance.asc(), ChunkRow.chunk_index.asc()).limit(top_k)

    with session_scope() as session:
        rows = session.execute(statement).all()
        results: list[dict[str, object]] = []
        for chunk, raw_distance in rows:
            cosine_distance = float(raw_distance)
            results.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "chunk_index": chunk.chunk_index,
                    "semantic_type": chunk.semantic_type,
                    "distance": cosine_distance,
                    "score": 1.0 - cosine_distance,
                    "text": chunk.text,
                    "content_text": chunk.content_text,
                    "token_count": chunk.token_count,
                    "pages": list(chunk.pages),
                    "section_path": list(chunk.section_path),
                    "source_element_ids": list(chunk.source_element_ids),
                }
            )
        return results

def lexical_search(
    *,
    document_id: str,
    query: str,
    top_k: int,
    semantic_types: list[str] | None = None,
    query_plan: LexicalQueryPlan | None = None,
) -> list[dict[str, object]]:
    """PostgreSQL FTS lexical candidates using OR-oriented content terms.

    Natural-language question scaffolding is removed deterministically before
    PostgreSQL applies English stemming. Candidates may match any retained term;
    ranking first rewards broader query-term coverage and then ``ts_rank_cd``.

    This remains a small-corpus baseline: no persisted tsvector/GIN index is
    required yet, and the public retrieval API remains independent of that
    future optimization.
    """

    plan = query_plan or build_lexical_query_plan(query)
    search_document = func.to_tsvector("english", func.coalesce(ChunkRow.text, ""))
    ts_query = func.to_tsquery("english", plan.tsquery_text)
    lexical_score = func.ts_rank_cd(search_document, ts_query).label("lexical_score")

    # Count how many normalized query terms match each chunk. This gives the
    # lexical baseline an interpretable coverage signal instead of allowing one
    # repeated generic word to dominate candidate order.
    term_match_expressions = [
        case(
            (
                search_document.op("@@")(func.plainto_tsquery("english", term)),
                1,
            ),
            else_=0,
        )
        for term in plan.terms
    ]
    matched_term_count = term_match_expressions[0]
    for expression in term_match_expressions[1:]:
        matched_term_count = matched_term_count + expression
    matched_term_count = matched_term_count.label("matched_term_count")

    statement = (
        select(ChunkRow, lexical_score, matched_term_count)
        .where(
            ChunkRow.document_id == document_id,
            search_document.op("@@")(ts_query),
        )
    )
    if semantic_types:
        statement = statement.where(ChunkRow.semantic_type.in_(semantic_types))
    statement = statement.order_by(
        matched_term_count.desc(),
        lexical_score.desc(),
        ChunkRow.chunk_index.asc(),
    ).limit(top_k)

    with session_scope() as session:
        rows = session.execute(statement).all()
        results: list[dict[str, object]] = []
        for chunk, raw_score, raw_match_count in rows:
            match_count = int(raw_match_count or 0)
            results.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "chunk_index": chunk.chunk_index,
                    "semantic_type": chunk.semantic_type,
                    "score": float(raw_score),
                    "matched_term_count": match_count,
                    "term_coverage": match_count / len(plan.terms),
                    "text": chunk.text,
                    "content_text": chunk.content_text,
                    "token_count": chunk.token_count,
                    "pages": list(chunk.pages),
                    "section_path": list(chunk.section_path),
                    "source_element_ids": list(chunk.source_element_ids),
                }
            )
        return results



def chunks_by_indices(document_id: str, chunk_indices: set[int]) -> dict[int, dict[str, object]]:
    """Fetch Stage-5 structural metadata for a bounded set of chunk indices."""

    if not chunk_indices:
        return {}
    with session_scope() as session:
        rows = session.scalars(
            select(ChunkRow)
            .where(
                ChunkRow.document_id == document_id,
                ChunkRow.chunk_index.in_(sorted(chunk_indices)),
            )
            .order_by(ChunkRow.chunk_index)
        ).all()
        return {
            int(row.chunk_index): {
                "chunk_id": row.chunk_id,
                "chunk_index": row.chunk_index,
                "semantic_type": row.semantic_type,
                "text": row.text,
                "content_text": row.content_text,
                "token_count": row.token_count,
                "pages": list(row.pages),
                "section_path": list(row.section_path),
                "source_element_ids": list(row.source_element_ids),
                "context_element_ids": list(row.context_element_ids),
                "refinement_tags": list(row.refinement_tags),
                "source_table_ids": list(row.source_table_ids),
                "relationship_ids": list(row.relationship_ids),
            }
            for row in rows
        }

def chunk_count(document_id: str) -> int:
    with session_scope() as session:
        return int(
            session.scalar(select(func.count()).select_from(ChunkRow).where(ChunkRow.document_id == document_id)) or 0
        )


def database_counts() -> dict[str, int]:
    from app.db.models import EvaluationQuestionRow, EvaluationRunRow

    with session_scope() as session:
        return {
            "documents": int(session.scalar(select(func.count()).select_from(DocumentRow)) or 0),
            "chunks": int(session.scalar(select(func.count()).select_from(ChunkRow)) or 0),
            "embeddings": int(session.scalar(select(func.count()).select_from(ChunkEmbeddingRow)) or 0),
            "evaluation_questions": int(session.scalar(select(func.count()).select_from(EvaluationQuestionRow)) or 0),
            "evaluation_runs": int(session.scalar(select(func.count()).select_from(EvaluationRunRow)) or 0),
        }
