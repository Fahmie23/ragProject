from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.schemas import (
    ContextExpandedRetrievalRequest,
    ContextExpandedRetrievalResponse,
    DenseRetrievalHit,
    DenseRetrievalRequest,
    DenseRetrievalResponse,
    HybridRetrievalHit,
    HybridRetrievalRequest,
    HybridRetrievalResponse,
    LexicalRetrievalHit,
    LexicalRetrievalRequest,
    LexicalRetrievalResponse,
    RerankedRetrievalHit,
    RerankedRetrievalRequest,
    RerankedRetrievalResponse,
)
from app.services.storage import read_metadata


router = APIRouter(prefix="/api/retrieval", tags=["retrieval"])


def _require_document(document_id: str) -> None:
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="Retrieval requires PostgreSQL + pgvector.")
    if not read_metadata(document_id):
        raise HTTPException(status_code=404, detail="Document not found.")


def _require_complete_embeddings(document_id: str, model_name: str):
    from app.db.repository import embedding_status

    status = embedding_status(document_id, model_name)
    if int(status["chunk_count"]) == 0:
        raise HTTPException(status_code=409, detail="No Stage 5 chunks are synchronized to PostgreSQL for this document.")
    if int(status["embedded_chunk_count"]) == 0:
        raise HTTPException(status_code=409, detail="Generate Stage 6 embeddings before running dense or hybrid retrieval.")
    if not bool(status["complete"]):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Embedding coverage is incomplete for {model_name}: "
                f"{status['embedded_chunk_count']}/{status['chunk_count']} chunks."
            ),
        )
    return status


def _build_encoder(model_name: str, device: str | None):
    from app.services.embeddings import EmbeddingDeviceError, EmbeddingEncoder

    try:
        return EmbeddingEncoder(model_name, device=device)
    except EmbeddingDeviceError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "embedding_device_unavailable",
                "message": str(exc),
                "requested_device": exc.requested_device,
            },
        ) from exc


@router.post("/dense", response_model=DenseRetrievalResponse)
def dense_retrieval(request: DenseRetrievalRequest) -> DenseRetrievalResponse:
    _require_document(request.document_id)

    from app.db.repository import dense_search

    model_name = request.embedding_model or settings.embedding_model
    status = _require_complete_embeddings(request.document_id, model_name)
    encoder = _build_encoder(model_name, request.embedding_device)
    query_vector = encoder.encode_query(request.query)
    rows = dense_search(
        document_id=request.document_id,
        embedding_model=model_name,
        query_vector=query_vector,
        top_k=request.top_k,
        semantic_types=request.semantic_types or None,
    )
    hits = [DenseRetrievalHit(rank=index + 1, **row) for index, row in enumerate(rows)]
    return DenseRetrievalResponse(
        document_id=request.document_id,
        query=request.query.strip(),
        embedding_model=model_name,
        requested_device=encoder.requested_device,
        resolved_device=encoder.device,
        top_k=request.top_k,
        embedded_chunk_count=int(status["embedded_chunk_count"]),
        total_chunk_count=int(status["chunk_count"]),
        hits=hits,
    )


@router.post("/lexical", response_model=LexicalRetrievalResponse)
def lexical_retrieval(request: LexicalRetrievalRequest) -> LexicalRetrievalResponse:
    _require_document(request.document_id)

    from app.db.repository import chunk_count, lexical_search
    from app.services.lexical import build_lexical_query_plan

    total_chunks = chunk_count(request.document_id)
    if total_chunks == 0:
        raise HTTPException(status_code=409, detail="No Stage 5 chunks are synchronized to PostgreSQL for this document.")

    lexical_plan = build_lexical_query_plan(request.query)
    rows = lexical_search(
        document_id=request.document_id,
        query=request.query,
        top_k=request.top_k,
        semantic_types=request.semantic_types or None,
        query_plan=lexical_plan,
    )
    hits = [LexicalRetrievalHit(rank=index + 1, **row) for index, row in enumerate(rows)]
    return LexicalRetrievalResponse(
        document_id=request.document_id,
        query=request.query.strip(),
        top_k=request.top_k,
        total_chunk_count=total_chunks,
        lexical_query_mode=lexical_plan.mode,
        lexical_terms=list(lexical_plan.terms),
        lexical_tsquery=lexical_plan.tsquery_text,
        hits=hits,
    )


@router.post("/hybrid", response_model=HybridRetrievalResponse)
def hybrid_retrieval(request: HybridRetrievalRequest) -> HybridRetrievalResponse:
    _require_document(request.document_id)

    from app.db.repository import dense_search, lexical_search
    from app.services.lexical import build_lexical_query_plan
    from app.services.retrieval import reciprocal_rank_fusion

    model_name = request.embedding_model or settings.embedding_model
    status = _require_complete_embeddings(request.document_id, model_name)
    encoder = _build_encoder(model_name, request.embedding_device)
    query_vector = encoder.encode_query(request.query)

    dense_rows = dense_search(
        document_id=request.document_id,
        embedding_model=model_name,
        query_vector=query_vector,
        top_k=request.candidate_k,
        semantic_types=request.semantic_types or None,
    )
    lexical_plan = build_lexical_query_plan(request.query)
    lexical_rows = lexical_search(
        document_id=request.document_id,
        query=request.query,
        top_k=request.candidate_k,
        semantic_types=request.semantic_types or None,
        query_plan=lexical_plan,
    )
    fused_rows = reciprocal_rank_fusion(
        dense_rows,
        lexical_rows,
        top_k=request.top_k,
        rrf_k=request.rrf_k,
        dense_weight=request.dense_weight,
        lexical_weight=request.lexical_weight,
    )
    hits = [HybridRetrievalHit(**row) for row in fused_rows]

    return HybridRetrievalResponse(
        document_id=request.document_id,
        query=request.query.strip(),
        embedding_model=model_name,
        requested_device=encoder.requested_device,
        resolved_device=encoder.device,
        top_k=request.top_k,
        candidate_k=request.candidate_k,
        embedded_chunk_count=int(status["embedded_chunk_count"]),
        total_chunk_count=int(status["chunk_count"]),
        rrf_k=request.rrf_k,
        dense_weight=request.dense_weight,
        lexical_weight=request.lexical_weight,
        lexical_query_mode=lexical_plan.mode,
        lexical_terms=list(lexical_plan.terms),
        lexical_tsquery=lexical_plan.tsquery_text,
        hits=hits,
    )


def _build_reranker(model_name: str, device: str | None, batch_size: int | None):
    from app.services.reranking import Reranker, RerankerDeviceError

    try:
        return Reranker(model_name, device=device, batch_size=batch_size)
    except RerankerDeviceError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "reranker_device_unavailable",
                "message": str(exc),
                "requested_device": exc.requested_device,
            },
        ) from exc


@router.post("/hybrid-rerank", response_model=RerankedRetrievalResponse)
def hybrid_reranked_retrieval(request: RerankedRetrievalRequest) -> RerankedRetrievalResponse:
    """Stage 8: rerank the deduplicated Dense Top-N + Lexical Top-N union."""

    _require_document(request.document_id)

    from app.db.repository import dense_search, lexical_search
    from app.services.lexical import build_lexical_query_plan
    from app.services.reranking import RerankerCompatibilityError
    from app.services.retrieval import reciprocal_rank_fusion, rerank_candidate_union

    embedding_model = request.embedding_model or settings.embedding_model
    status = _require_complete_embeddings(request.document_id, embedding_model)
    encoder = _build_encoder(embedding_model, request.embedding_device)
    query_vector = encoder.encode_query(request.query)

    dense_rows = dense_search(
        document_id=request.document_id,
        embedding_model=embedding_model,
        query_vector=query_vector,
        top_k=request.candidate_k,
        semantic_types=request.semantic_types or None,
    )
    lexical_plan = build_lexical_query_plan(request.query)
    lexical_rows = lexical_search(
        document_id=request.document_id,
        query=request.query,
        top_k=request.candidate_k,
        semantic_types=request.semantic_types or None,
        query_plan=lexical_plan,
    )

    # Build the complete deduplicated union. RRF order is preserved as useful
    # trace metadata and a deterministic tie-breaker, but Stage 8 does not cut
    # the pool down to Hybrid Top-K before reranking.
    union_count = len({str(row["chunk_id"]) for row in [*dense_rows, *lexical_rows]})
    candidate_rows = reciprocal_rank_fusion(
        dense_rows,
        lexical_rows,
        top_k=max(1, union_count),
        rrf_k=request.rrf_k,
        dense_weight=request.dense_weight,
        lexical_weight=request.lexical_weight,
    ) if union_count else []

    reranker_model = request.reranker_model or settings.reranker_model
    reranker = _build_reranker(reranker_model, request.reranker_device, request.reranker_batch_size)

    try:
        reranker_scores = reranker.score(
            request.query,
            [row["text"] for row in candidate_rows],
        )
    except RerankerCompatibilityError as exc:
        violations = []
        for item in exc.violations:
            index = int(item["index"])
            row = candidate_rows[index] if 0 <= index < len(candidate_rows) else None
            violations.append(
                {
                    **item,
                    "chunk_id": row.get("chunk_id") if row else None,
                    "chunk_index": row.get("chunk_index") if row else None,
                }
            )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "reranker_input_too_long",
                "message": str(exc),
                "reranker_model": reranker_model,
                "reranker_max_length": reranker.max_length,
                "violations": violations,
            },
        ) from exc

    reranked_rows, candidate_union_count = rerank_candidate_union(
        dense_rows,
        lexical_rows,
        reranker_scores,
        top_k=request.top_k,
        rrf_k=request.rrf_k,
        dense_weight=request.dense_weight,
        lexical_weight=request.lexical_weight,
    )
    hits = [RerankedRetrievalHit(**row) for row in reranked_rows]

    return RerankedRetrievalResponse(
        document_id=request.document_id,
        query=request.query.strip(),
        embedding_model=embedding_model,
        embedding_requested_device=encoder.requested_device,
        embedding_resolved_device=encoder.device,
        reranker_model=reranker_model,
        reranker_requested_device=reranker.requested_device,
        reranker_resolved_device=reranker.device,
        reranker_batch_size=reranker.batch_size,
        reranker_max_length=reranker.max_length,
        top_k=request.top_k,
        candidate_k=request.candidate_k,
        candidate_union_count=candidate_union_count,
        embedded_chunk_count=int(status["embedded_chunk_count"]),
        total_chunk_count=int(status["chunk_count"]),
        rrf_k=request.rrf_k,
        dense_weight=request.dense_weight,
        lexical_weight=request.lexical_weight,
        lexical_query_mode=lexical_plan.mode,
        lexical_terms=list(lexical_plan.terms),
        lexical_tsquery=lexical_plan.tsquery_text,
        hits=hits,
    )

@router.post("/hybrid-rerank-context", response_model=ContextExpandedRetrievalResponse)
def hybrid_reranked_context_retrieval(request: ContextExpandedRetrievalRequest) -> ContextExpandedRetrievalResponse:
    """Stage 8.2: keep the Stage-8 ranking unchanged and assemble bounded structural context."""

    # Reuse the frozen Stage-8 ranking path verbatim. Context assembly occurs only
    # after the ranked hits have been finalized.
    ranked_response = hybrid_reranked_retrieval(
        RerankedRetrievalRequest(**request.model_dump(exclude={
            "context_max_forward_neighbors_per_seed",
            "context_max_backward_neighbors_per_seed",
            "context_max_page_gap",
            "context_max_chunks",
        }))
    )

    from app.db.repository import chunks_by_indices
    from app.services.context_assembly import (
        StructuralContextConfig,
        assemble_structural_context,
        required_neighbor_indices,
    )

    config = StructuralContextConfig(
        max_forward_neighbors_per_seed=request.context_max_forward_neighbors_per_seed,
        max_backward_neighbors_per_seed=request.context_max_backward_neighbors_per_seed,
        max_page_gap=request.context_max_page_gap,
        max_context_chunks=request.context_max_chunks,
        same_section_required=True,
        recursive=False,
    )
    ranked_rows = [hit.model_dump() for hit in ranked_response.hits]
    seed_indices = [int(hit["chunk_index"]) for hit in ranked_rows]
    needed_indices = required_neighbor_indices(seed_indices, config) | set(seed_indices)
    chunk_lookup = chunks_by_indices(request.document_id, needed_indices)
    # Ensure the exact ranked payload remains authoritative even if a mocked or
    # partially loaded repository lookup omits a seed.
    for row in ranked_rows:
        chunk_lookup.setdefault(int(row["chunk_index"]), row)

    context_chunks = assemble_structural_context(ranked_rows, chunk_lookup, config=config)
    seed_ids = {str(hit.chunk_id) for hit in ranked_response.hits}
    expanded_count = len({str(item["chunk_id"]) for item in context_chunks} - seed_ids)

    return ContextExpandedRetrievalResponse(
        **ranked_response.model_dump(),
        context_max_forward_neighbors_per_seed=config.max_forward_neighbors_per_seed,
        context_max_backward_neighbors_per_seed=config.max_backward_neighbors_per_seed,
        context_max_page_gap=config.max_page_gap,
        context_max_chunks=config.max_context_chunks,
        context_chunk_count=len(context_chunks),
        expanded_chunk_count=expanded_count,
        context_chunks=context_chunks,
    )

