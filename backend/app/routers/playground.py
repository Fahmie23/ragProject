from __future__ import annotations

from fastapi import APIRouter


router = APIRouter(prefix="/api/playground", tags=["playground"])


@router.get("/contract")
def playground_contract() -> dict:
    """Stage 14.1 source-of-truth contract for the future RAG Playground UI."""

    return {
        "contract_version": "stage14_playground_contract_v1",
        "live_query": {
            "endpoint": "/api/generation/answer",
            "method": "POST",
            "may_call_external_generation_provider": True,
            "production_profile_only": True,
            "request_configurable_retrieval": False,
        },
        "field_origins": [
            {
                "area": "answer",
                "fields": ["status", "answer", "cited_answer", "claims", "missing_information"],
                "source": "Stage 9 grounded generation plus Stage 10 deterministic citation assembly",
                "frontend_calculation_allowed": False,
            },
            {
                "area": "evidence",
                "fields": ["evidence", "used_evidence_ids", "context_strategy", "context_chunk_count", "expanded_chunk_count"],
                "source": "Frozen Retrieval-v1 Stage 8.2 structural context assembly exposed by generation",
                "frontend_calculation_allowed": False,
            },
            {
                "area": "citations",
                "fields": ["citations", "citation_version", "citation_validation"],
                "source": "Stage 10 deterministic citation provenance",
                "frontend_calculation_allowed": False,
            },
            {
                "area": "generation_trace",
                "fields": ["generation_provider", "generation_model", "prompt_version", "usage"],
                "source": "Stage 9 generation runtime metadata",
                "frontend_calculation_allowed": False,
            },
            {
                "area": "evaluation",
                "fields": ["summary metrics", "per-question metrics", "human semantic labels", "frozen response snapshots"],
                "source": "Frozen Stage 11 held-out evaluation artifacts",
                "frontend_calculation_allowed": False,
            },
        ],
        "evaluation": {
            "summary_endpoint": "/api/evaluation/answer-citation/summary",
            "questions_endpoint": "/api/evaluation/answer-citation/questions",
            "question_detail_endpoint_template": "/api/evaluation/answer-citation/questions/{question_id}",
            "read_only": True,
            "may_call_external_generation_provider": False,
            "may_modify_frozen_benchmark": False,
            "scope": "answer_citation_eval_heldout_v1 only",
        },
        "deferred_inspection": {
            "full_dense_lexical_rrf_reranker_trace": "Stage 14.3",
            "reason": "The current production generation response does not expose the full retrieval trace; Stage 14.1 will not fabricate it or execute retrieval twice.",
        },
        "frontend_rule": "React displays backend-owned facts and metrics; React does not calculate RAG rankings or evaluation scores.",
    }
