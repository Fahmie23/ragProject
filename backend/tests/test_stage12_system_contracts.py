from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.schemas import ContextExpandedRetrievalResponse, RerankedRetrievalHit, StructuralContextChunk
from app.services.citations import CitationSourceError, CitationValidationError
from app.services.generation import (
    GenerationConfigurationError,
    GenerationContextError,
    GenerationOutputError,
    GenerationProviderError,
)


def _fake_retrieval_response(*, with_context: bool = True) -> ContextExpandedRetrievalResponse:
    hit = RerankedRetrievalHit(
        rank=1,
        chunk_id="c1",
        chunk_index=1,
        semantic_type="clause",
        reranker_score=0.9,
        hybrid_candidate_rank=1,
        fusion_score=0.03,
        text="Primary evidence.",
        content_text="Primary evidence.",
        token_count=3,
        pages=[10],
        section_path=["8. CDD"],
        source_element_ids=["e1"],
    )
    context = StructuralContextChunk(
        context_order=1,
        chunk_id="c1",
        chunk_index=1,
        semantic_type="clause",
        source_rank=1,
        ranked_seed_rank=1,
        reasons=["ranked_seed"],
        attached_from_chunk_ids=[],
        text="Primary evidence.",
        content_text="Primary evidence." if with_context else "",
        token_count=3,
        pages=[10],
        section_path=["8. CDD"],
        source_element_ids=["e1"],
    )
    return ContextExpandedRetrievalResponse(
        document_id="doc",
        query="question",
        embedding_model="BAAI/bge-m3",
        embedding_requested_device="auto",
        embedding_resolved_device="cpu",
        reranker_model="BAAI/bge-reranker-v2-m3",
        reranker_requested_device="auto",
        reranker_resolved_device="cpu",
        reranker_batch_size=2,
        reranker_max_length=1024,
        top_k=5,
        candidate_k=20,
        candidate_union_count=1,
        embedded_chunk_count=1,
        total_chunk_count=1,
        lexical_tsquery="question",
        hits=[hit],
        context_chunk_count=1 if with_context else 0,
        expanded_chunk_count=0,
        context_chunks=[context] if with_context else [],
    )


def test_openapi_contains_stage12_critical_routes():
    schema = app.openapi()
    paths = schema["paths"]
    expected = {
        "/health",
        "/api/system/database",
        "/api/documents/upload",
        "/api/documents/{document_id}/extract",
        "/api/documents/{document_id}/structure",
        "/api/documents/{document_id}/chunks",
        "/api/retrieval/hybrid-rerank-context",
        "/api/generation/answer",
    }
    assert expected <= set(paths)
    assert "post" in paths["/api/generation/answer"]
    assert "post" in paths["/api/retrieval/hybrid-rerank-context"]


def test_health_is_ok_when_database_is_optional_and_unreachable(monkeypatch):
    import app.main as main

    monkeypatch.setattr(settings, "database_required", False)
    monkeypatch.setattr(main, "database_probe", lambda: {"reachable": False, "pgvector_enabled": False, "error": "offline"})
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_is_degraded_when_required_database_is_unreachable(monkeypatch):
    import app.main as main

    monkeypatch.setattr(settings, "database_required", True)
    monkeypatch.setattr(main, "database_probe", lambda: {"reachable": False, "pgvector_enabled": False, "error": "offline"})
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"


@pytest.mark.parametrize(
    ("probe", "message"),
    [
        ({"reachable": False, "pgvector_enabled": False, "error": "offline"}, "database is unavailable"),
        ({"reachable": True, "pgvector_enabled": False, "error": None}, "missing the pgvector extension"),
    ],
)
def test_lifespan_refuses_invalid_required_database(monkeypatch, probe, message):
    import app.main as main

    monkeypatch.setattr(settings, "database_required", True)
    monkeypatch.setattr(settings, "database_url", "postgresql://example")
    monkeypatch.setattr(main, "database_probe", lambda: probe)
    with pytest.raises(RuntimeError, match=message):
        with TestClient(app):
            pass


def test_system_generation_status_does_not_expose_api_secret(monkeypatch):
    monkeypatch.setattr(settings, "generation_api_key", "stage12-super-secret")
    monkeypatch.setenv("GROQ_API_KEY", "stage12-super-secret")
    response = TestClient(app).get("/api/system/generation")
    assert response.status_code == 200
    payload = response.json()
    assert payload["api_key_configured"] is True
    assert "stage12-super-secret" not in response.text


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/api/retrieval/dense", {"document_id": "doc", "query": "q"}),
        ("/api/retrieval/lexical", {"document_id": "doc", "query": "q"}),
        ("/api/retrieval/hybrid", {"document_id": "doc", "query": "q"}),
        ("/api/retrieval/hybrid-rerank", {"document_id": "doc", "query": "q"}),
        ("/api/retrieval/hybrid-rerank-context", {"document_id": "doc", "query": "q"}),
    ],
)
def test_retrieval_api_fails_closed_without_postgres(monkeypatch, path, payload):
    monkeypatch.setattr(settings, "database_url", None)
    response = TestClient(app).post(path, json=payload)
    assert response.status_code == 503
    assert "PostgreSQL" in str(response.json()["detail"])


def test_hybrid_request_contract_rejects_candidate_k_below_top_k():
    response = TestClient(app).post(
        "/api/retrieval/hybrid",
        json={"document_id": "doc", "query": "q", "top_k": 5, "candidate_k": 4},
    )
    assert response.status_code == 422
    assert "candidate_k" in response.text


def test_generation_api_deterministically_abstains_when_context_is_empty(monkeypatch):
    from app.routers import generation as router

    monkeypatch.setattr(router, "hybrid_reranked_context_retrieval", lambda request: _fake_retrieval_response(with_context=False))

    class MustNotConstruct:
        def __init__(self):
            raise AssertionError("generator must not be constructed for empty evidence")

    monkeypatch.setattr(router, "OpenAICompatibleGenerator", MustNotConstruct)
    response = TestClient(app).post("/api/generation/answer", json={"document_id": "doc", "question": "question"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "insufficient_evidence"
    assert payload["claims"] == []
    assert payload["citations"] == []
    assert payload["citation_version"] == "deterministic_citations_v1_2"
    assert payload["retrieval_profile"] == "retrieval_v1_stage8_2_top5"


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (GenerationConfigurationError("missing key"), 503, "generation_not_configured"),
        (GenerationContextError("too large"), 409, "generation_context_too_large"),
        (GenerationOutputError("bad json"), 502, "invalid_grounded_generation"),
        (GenerationProviderError("provider failed", status_code=429, detail="rate"), 502, "generation_provider_error"),
    ],
)
def test_generation_api_maps_generation_failures_to_stable_http_contract(monkeypatch, error, status_code, code):
    from app.routers import generation as router

    monkeypatch.setattr(router, "hybrid_reranked_context_retrieval", lambda request: _fake_retrieval_response())
    monkeypatch.setattr(router, "validate_context_budget", lambda system, user: None)

    class FailingGenerator:
        def generate(self, system_prompt, user_prompt):
            raise error

    monkeypatch.setattr(router, "OpenAICompatibleGenerator", FailingGenerator)
    response = TestClient(app).post("/api/generation/answer", json={"document_id": "doc", "question": "question"})
    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == code
    if isinstance(error, GenerationProviderError):
        assert response.json()["detail"]["provider_status_code"] == 429


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (CitationSourceError("missing source"), "citation_source_unavailable"),
        (CitationValidationError("bad provenance"), "citation_provenance_invalid"),
    ],
)
def test_generation_api_fails_closed_on_citation_errors(monkeypatch, error, code):
    from app.routers import generation as router

    monkeypatch.setattr(router, "hybrid_reranked_context_retrieval", lambda request: _fake_retrieval_response())
    monkeypatch.setattr(router, "validate_context_budget", lambda system, user: None)

    class GoodGenerator:
        def generate(self, system_prompt, user_prompt):
            return {
                "content": '{"status":"answered","claims":[{"text":"Supported answer.","evidence_ids":["E1"]}],"missing_information":[]}',
                "usage": None,
            }

    monkeypatch.setattr(router, "OpenAICompatibleGenerator", GoodGenerator)
    monkeypatch.setattr(router, "build_citation_bundle", lambda *args, **kwargs: (_ for _ in ()).throw(error))
    response = TestClient(app).post("/api/generation/answer", json={"document_id": "doc", "question": "question"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == code
