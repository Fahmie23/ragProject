from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.routers.retrieval import hybrid_reranked_context_retrieval
from app.schemas import (
    CitationValidationSummary,
    ContextExpandedRetrievalRequest,
    GenerationEvidence,
    GenerationUsage,
    GroundedAnswerRequest,
    GroundedAnswerResponse,
    GroundedClaim,
    SourceCitation,
)
from app.services.citations import (
    CitationSourceError,
    CitationValidationError,
    build_citation_bundle,
)
from app.services.generation import (
    PROMPT_VERSION,
    PRODUCTION_RETRIEVAL,
    PRODUCTION_RETRIEVAL_PROFILE,
    GenerationConfigurationError,
    GenerationContextError,
    GenerationOutputError,
    GenerationProviderError,
    OpenAICompatibleGenerator,
    build_evidence_package,
    build_grounded_prompts,
    validate_context_budget,
    validate_model_decision,
)

router = APIRouter(prefix="/api/generation", tags=["generation"])


@router.post("/answer", response_model=GroundedAnswerResponse)
def grounded_answer(request: GroundedAnswerRequest) -> GroundedAnswerResponse:
    """Stage 10: grounded answer + deterministic citations over frozen Retrieval-v1 evidence.

    Retrieval parameters are intentionally not request-configurable here. The RAG
    Playground still exposes retrieval experiments separately, while generation uses
    the exact production profile evaluated on the held-out benchmark.
    """

    cfg = PRODUCTION_RETRIEVAL
    retrieval = hybrid_reranked_context_retrieval(
        ContextExpandedRetrievalRequest(
            document_id=request.document_id,
            query=request.question,
            top_k=cfg.top_k,
            candidate_k=cfg.candidate_k,
            rrf_k=cfg.rrf_k,
            dense_weight=cfg.dense_weight,
            lexical_weight=cfg.lexical_weight,
            embedding_device="auto",
            reranker_model=settings.reranker_model,
            reranker_device="auto",
            context_max_forward_neighbors_per_seed=cfg.context_max_forward_neighbors_per_seed,
            context_max_backward_neighbors_per_seed=cfg.context_max_backward_neighbors_per_seed,
            context_max_page_gap=cfg.context_max_page_gap,
            context_max_chunks=cfg.context_max_chunks,
        )
    )

    evidence_rows = build_evidence_package([item.model_dump() for item in retrieval.context_chunks])
    evidence = [GenerationEvidence(**item) for item in evidence_rows]

    # No model call when retrieval produced no usable evidence. This is deterministic
    # abstention and avoids paying for a completion that cannot be grounded.
    if not evidence:
        return GroundedAnswerResponse(
            document_id=request.document_id,
            question=request.question.strip(),
            status="insufficient_evidence",
            answer="The retrieved evidence is insufficient to answer this question reliably.",
            cited_answer="The retrieved evidence is insufficient to answer this question reliably.",
            claims=[],
            used_evidence_ids=[],
            missing_information=["No usable document evidence was retrieved."],
            evidence=[],
            generation_provider=settings.generation_provider,
            generation_model=settings.generation_model,
            prompt_version=PROMPT_VERSION,
            generation_temperature=settings.generation_temperature,
            generation_max_tokens=settings.generation_max_tokens,
            generation_json_mode=settings.generation_json_mode,
            usage=None,
            retrieval_profile=PRODUCTION_RETRIEVAL_PROFILE,
            retrieval_top_k=cfg.top_k,
            retrieval_candidate_k=cfg.candidate_k,
            retrieval_rrf_k=cfg.rrf_k,
            retrieval_dense_weight=cfg.dense_weight,
            retrieval_lexical_weight=cfg.lexical_weight,
            context_strategy=retrieval.context_strategy,
            context_chunk_count=retrieval.context_chunk_count,
            expanded_chunk_count=retrieval.expanded_chunk_count,
            retrieval_trace=retrieval.retrieval_trace,
        )

    system_prompt, user_prompt = build_grounded_prompts(request.question, evidence_rows)
    try:
        validate_context_budget(system_prompt, user_prompt)
        generator = OpenAICompatibleGenerator()
        completion = generator.generate(system_prompt, user_prompt)
        decision = validate_model_decision(completion["content"], evidence_rows)
    except GenerationConfigurationError as exc:
        raise HTTPException(status_code=503, detail={"code": "generation_not_configured", "message": str(exc)}) from exc
    except GenerationContextError as exc:
        raise HTTPException(status_code=409, detail={"code": "generation_context_too_large", "message": str(exc)}) from exc
    except GenerationOutputError as exc:
        raise HTTPException(status_code=502, detail={"code": "invalid_grounded_generation", "message": str(exc)}) from exc
    except GenerationProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "generation_provider_error",
                "message": str(exc),
                "provider_status_code": exc.status_code,
                "provider_detail": exc.detail,
            },
        ) from exc

    try:
        citation_bundle = build_citation_bundle(request.document_id, decision["claims"], evidence_rows)
    except CitationSourceError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "citation_source_unavailable", "message": str(exc)},
        ) from exc
    except CitationValidationError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "citation_provenance_invalid", "message": str(exc)},
        ) from exc

    cited_answer = citation_bundle["cited_answer"] if decision["status"] == "answered" else decision["answer"]

    return GroundedAnswerResponse(
        document_id=request.document_id,
        question=request.question.strip(),
        status=decision["status"],
        answer=decision["answer"],
        cited_answer=cited_answer,
        claims=[GroundedClaim(**item) for item in citation_bundle["claims"]],
        used_evidence_ids=decision["used_evidence_ids"],
        missing_information=decision["missing_information"],
        evidence=evidence,
        citations=[SourceCitation(**item) for item in citation_bundle["citations"]],
        citation_version=citation_bundle["citation_version"],
        citation_validation=CitationValidationSummary(**citation_bundle["citation_validation"]),
        generation_provider=settings.generation_provider,
        generation_model=settings.generation_model,
        prompt_version=PROMPT_VERSION,
        generation_temperature=settings.generation_temperature,
        generation_max_tokens=settings.generation_max_tokens,
        generation_json_mode=settings.generation_json_mode,
        usage=GenerationUsage(**completion["usage"]) if completion.get("usage") else None,
        retrieval_profile=PRODUCTION_RETRIEVAL_PROFILE,
        retrieval_top_k=cfg.top_k,
        retrieval_candidate_k=cfg.candidate_k,
        retrieval_rrf_k=cfg.rrf_k,
        retrieval_dense_weight=cfg.dense_weight,
        retrieval_lexical_weight=cfg.lexical_weight,
        context_strategy=retrieval.context_strategy,
        context_chunk_count=retrieval.context_chunk_count,
        expanded_chunk_count=retrieval.expanded_chunk_count,
        retrieval_trace=retrieval.retrieval_trace,
    )
