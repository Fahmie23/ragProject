from __future__ import annotations

from types import ModuleType
import sys

import pytest
from pydantic import ValidationError

from app.schemas import RerankedRetrievalRequest
from app.services.retrieval import reciprocal_rank_fusion, rerank_candidate_union


def _dense(chunk_id: str, index: int, score: float) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "chunk_index": index,
        "semantic_type": "clause",
        "score": score,
        "distance": 1.0 - score,
        "text": f"Section: Test\n\ntext {chunk_id}",
        "content_text": f"content {chunk_id}",
        "token_count": 10,
        "pages": [1],
        "section_path": ["Section"],
        "source_element_ids": [f"e-{chunk_id}"],
    }


def _lexical(chunk_id: str, index: int, score: float) -> dict[str, object]:
    row = _dense(chunk_id, index, 0.0)
    row.pop("distance")
    row["score"] = score
    row["matched_term_count"] = 2
    row["term_coverage"] = 0.5
    return row


def test_reranker_uses_union_instead_of_hybrid_top_k():
    dense = [_dense("dense-first", 1, 0.9), _dense("answer", 2, 0.8)]
    lexical = [_lexical("lexical-first", 3, 0.9), _lexical("dense-first", 1, 0.8)]

    union = reciprocal_rank_fusion(dense, lexical, top_k=3)
    assert {row["chunk_id"] for row in union} == {"dense-first", "answer", "lexical-first"}

    # Scores correspond to the deterministic union order. Give the answer the
    # highest cross-encoder score even though it is dense-only.
    scores = [10.0 if row["chunk_id"] == "answer" else -1.0 for row in union]
    reranked, count = rerank_candidate_union(dense, lexical, scores, top_k=2)

    assert count == 3
    assert reranked[0]["chunk_id"] == "answer"
    assert reranked[0]["rank"] == 1
    assert reranked[0]["dense_rank"] == 2
    assert reranked[0]["lexical_rank"] is None
    assert reranked[0]["hybrid_candidate_rank"] >= 1
    assert reranked[0]["reranker_score"] == pytest.approx(10.0)
    assert "reranker_normalized_score" not in reranked[0]


def test_reranker_tie_breaks_with_hybrid_candidate_rank():
    dense = [_dense("a", 1, 0.9), _dense("b", 2, 0.8)]
    reranked, _ = rerank_candidate_union(dense, [], [0.5, 0.5], top_k=2)
    assert [row["chunk_id"] for row in reranked] == ["a", "b"]


def test_reranked_request_rejects_candidate_pool_smaller_than_top_k():
    with pytest.raises(ValidationError, match="candidate_k"):
        RerankedRetrievalRequest(document_id="doc", query="test", top_k=10, candidate_k=5)


def test_stage8_endpoint_reranks_full_candidate_union(monkeypatch):
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
            return [1.0, 0.0]

    monkeypatch.setattr(retrieval, "_build_encoder", lambda model_name, device: FakeEncoder())

    class FakeReranker:
        requested_device = "auto"
        device = "cuda"
        batch_size = 2
        max_length = 1024

        def score(self, query: str, passages: list[str]):
            # The dense-only "answer" candidate must remain available. Score by text.
            return [9.0 if "answer" in passage else -2.0 for passage in passages]

    monkeypatch.setattr(retrieval, "_build_reranker", lambda model_name, device, batch_size: FakeReranker())

    fake_repository = ModuleType("app.db.repository")
    fake_repository.dense_search = lambda **kwargs: [
        _dense("dense-first", 1, 0.90),
        _dense("answer", 2, 0.80),
    ]
    fake_repository.lexical_search = lambda **kwargs: [
        _lexical("lexical-first", 3, 0.90),
        _lexical("dense-first", 1, 0.80),
    ]
    monkeypatch.setitem(sys.modules, "app.db.repository", fake_repository)

    response = retrieval.hybrid_reranked_retrieval(
        RerankedRetrievalRequest(
            document_id="doc",
            query="what information is required?",
            top_k=2,
            candidate_k=20,
            embedding_model="BAAI/bge-m3",
            reranker_model="BAAI/bge-reranker-v2-m3",
        )
    )

    assert response.candidate_strategy == "dense_lexical_union"
    assert response.candidate_union_count == 3
    assert response.reranker_resolved_device == "cuda"
    assert response.hits[0].chunk_id == "answer"
    assert response.hits[0].reranker_score == pytest.approx(9.0)
    assert response.hits[0].dense_rank == 2
    assert response.hits[0].lexical_rank is None


def test_reranker_runtime_status_does_not_load_model(monkeypatch):
    from app.services import reranking

    monkeypatch.setattr(
        reranking,
        "_torch_runtime",
        lambda: {
            "torch_available": True,
            "cuda_available": True,
            "cuda_device_count": 1,
            "cuda_devices": [{"index": 0, "name": "Fake GPU"}],
        },
    )
    monkeypatch.setattr(reranking, "resolve_reranker_device", lambda device=None: ("auto", "cuda"))

    status = reranking.reranker_runtime_status()
    assert status["reranker_model"] == "BAAI/bge-reranker-v2-m3"
    assert status["resolved_device"] == "cuda"
    assert status["reranker_max_length"] == 1024
