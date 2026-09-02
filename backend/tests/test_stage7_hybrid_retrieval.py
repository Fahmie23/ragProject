from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import HybridRetrievalRequest, LexicalRetrievalRequest
from app.services.lexical import build_lexical_query_plan
from app.services.retrieval import reciprocal_rank_fusion


def _dense(chunk_id: str, index: int, score: float) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "chunk_index": index,
        "semantic_type": "clause",
        "score": score,
        "distance": 1.0 - score,
        "text": f"text {chunk_id}",
        "content_text": f"content {chunk_id}",
        "token_count": 10,
        "pages": [1],
        "section_path": ["Section"],
        "source_element_ids": [f"e-{chunk_id}"],
    }


def _lexical(
    chunk_id: str,
    index: int,
    score: float,
    *,
    matched_term_count: int = 2,
    term_coverage: float = 0.5,
) -> dict[str, object]:
    row = _dense(chunk_id, index, 0.0)
    row.pop("distance")
    row["score"] = score
    row["matched_term_count"] = matched_term_count
    row["term_coverage"] = term_coverage
    return row



def test_lexical_query_plan_removes_question_scaffolding_and_uses_or_terms():
    plan = build_lexical_query_plan("What are the requirements for delayed verification?")

    assert plan.mode == "or_content_terms_v1"
    assert plan.terms == ("requirements", "delayed", "verification")
    assert plan.tsquery_text == "requirements | delayed | verification"


def test_lexical_query_plan_keeps_paraphrase_content_terms_and_deduplicates():
    plan = build_lexical_query_plan(
        "What should an institution do when a customer cannot complete identity verification in time, time?"
    )

    assert plan.terms == ("institution", "customer", "cannot", "complete", "identity", "verification", "time")
    assert plan.tsquery_text.count("time") == 1


def test_rrf_rewards_candidates_supported_by_both_retrievers():
    dense = [_dense("dense-only", 1, 0.90), _dense("both", 2, 0.80)]
    lexical = [_lexical("both", 2, 0.75), _lexical("lexical-only", 3, 0.70)]

    fused = reciprocal_rank_fusion(dense, lexical, top_k=3, rrf_k=60)

    assert [row["chunk_id"] for row in fused] == ["both", "dense-only", "lexical-only"]
    assert fused[0]["rank"] == 1
    assert fused[0]["dense_rank"] == 2
    assert fused[0]["lexical_rank"] == 1
    assert fused[0]["lexical_matched_term_count"] == 2
    assert fused[0]["lexical_term_coverage"] == pytest.approx(0.5)
    assert fused[0]["fusion_score"] == pytest.approx((1 / 62) + (1 / 61))


def test_rrf_keeps_dense_only_candidate_when_lexical_has_no_match():
    fused = reciprocal_rank_fusion([_dense("c1", 1, 0.88)], [], top_k=5)
    assert len(fused) == 1
    assert fused[0]["chunk_id"] == "c1"
    assert fused[0]["dense_rank"] == 1
    assert fused[0]["lexical_rank"] is None


def test_hybrid_request_rejects_candidate_pool_smaller_than_final_top_k():
    with pytest.raises(ValidationError, match="candidate_k"):
        HybridRetrievalRequest(document_id="doc", query="test", top_k=10, candidate_k=5)


def test_hybrid_endpoint_returns_traceable_dense_and_lexical_ranks(monkeypatch):
    import sys
    from types import ModuleType
    from app.routers import retrieval

    monkeypatch.setattr(retrieval, "_require_document", lambda document_id: None)
    monkeypatch.setattr(
        retrieval,
        "_require_complete_embeddings",
        lambda document_id, model_name: {"chunk_count": 284, "embedded_chunk_count": 284, "complete": True},
    )

    class FakeEncoder:
        requested_device = "auto"
        device = "cuda"

        def encode_query(self, query: str):
            assert query == "delayed verification"
            return [1.0, 0.0]

    monkeypatch.setattr(retrieval, "_build_encoder", lambda model_name, device: FakeEncoder())
    fake_repository = ModuleType("app.db.repository")
    fake_repository.dense_search = lambda **kwargs: [_dense("dense-first", 1, 0.90), _dense("both", 2, 0.80)]
    fake_repository.lexical_search = lambda **kwargs: [_lexical("both", 2, 0.70), _lexical("lexical-second", 3, 0.60)]
    monkeypatch.setitem(sys.modules, "app.db.repository", fake_repository)

    response = retrieval.hybrid_retrieval(
        HybridRetrievalRequest(
            document_id="doc",
            query="delayed verification",
            top_k=3,
            candidate_k=20,
            embedding_model="BAAI/bge-m3",
            embedding_device="auto",
        )
    )

    assert response.resolved_device == "cuda"
    assert response.fusion_method == "reciprocal_rank_fusion"
    assert response.lexical_query_mode == "or_content_terms_v1"
    assert response.lexical_terms == ["delayed", "verification"]
    assert response.lexical_tsquery == "delayed | verification"
    assert response.hits[0].chunk_id == "both"
    assert response.hits[0].dense_rank == 2
    assert response.hits[0].lexical_rank == 1


def test_lexical_endpoint_does_not_require_embedding_runtime(monkeypatch):
    import sys
    from types import ModuleType
    from app.routers import retrieval

    monkeypatch.setattr(retrieval, "_require_document", lambda document_id: None)
    fake_repository = ModuleType("app.db.repository")
    fake_repository.chunk_count = lambda document_id: 284
    fake_repository.lexical_search = lambda **kwargs: [_lexical("c1", 1, 0.5)]
    monkeypatch.setitem(sys.modules, "app.db.repository", fake_repository)

    response = retrieval.lexical_retrieval(
        LexicalRetrievalRequest(document_id="doc", query="politically exposed person", top_k=5)
    )

    assert response.total_chunk_count == 284
    assert response.ranking_method == "postgresql_fts_term_coverage_then_ts_rank_cd"
    assert response.lexical_query_mode == "or_content_terms_v1"
    assert response.lexical_terms == ["politically", "exposed", "person"]
    assert response.lexical_tsquery == "politically | exposed | person"
    assert response.hits[0].chunk_id == "c1"
