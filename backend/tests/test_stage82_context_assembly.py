from __future__ import annotations

from app.services.context_assembly import StructuralContextConfig, assemble_structural_context


def _chunk(index: int, kind: str, content: str, *, section: str = "S", page: int = 1):
    return {
        "chunk_id": f"c{index}",
        "chunk_index": index,
        "semantic_type": kind,
        "text": content,
        "content_text": content,
        "token_count": 10,
        "pages": [page],
        "section_path": [section],
        "source_element_ids": [f"e{index}"],
    }


def _hit(chunk: dict, rank: int):
    return {**chunk, "rank": rank, "reranker_score": 1.0}


def test_context_expansion_attaches_list_continuation_without_changing_ranked_seed():
    seed = _chunk(90, "clause", "(f) Prescribed institutions; and", page=34)
    continuation = _chunk(91, "list_item", "(g) Licensed entities", page=35)
    lookup = {90: seed, 91: continuation}

    context = assemble_structural_context([_hit(seed, 1)], lookup)

    assert [item["chunk_id"] for item in context] == ["c90", "c91"]
    assert context[0]["ranked_seed_rank"] == 1
    assert context[1]["ranked_seed_rank"] is None
    assert context[1]["source_rank"] == 1
    assert "continuation_list_item" in context[1]["reasons"]


def test_context_expansion_attaches_two_introduced_children_and_stops_at_new_clause():
    intro = _chunk(180, "clause", "2.1 The RBA entails two (2) assessments:")
    child_a = _chunk(181, "mixed", "Business-based Risk Assessment")
    child_b = _chunk(182, "mixed", "Relationship-based Risk Assessment")
    new_clause = _chunk(183, "clause", "2.2 The RBA must be tailored...")
    lookup = {180: intro, 181: child_a, 182: child_b, 183: new_clause}

    context = assemble_structural_context([_hit(intro, 1)], lookup)

    assert [item["chunk_id"] for item in context] == ["c180", "c181", "c182"]
    assert all(item["source_rank"] == 1 for item in context)
    assert "c183" not in {item["chunk_id"] for item in context}


def test_context_expansion_attaches_immediately_following_table():
    seed = _chunk(242, "clause", "The institution is required to report to the following authorities.", page=89)
    table = _chunk(243, "table", "Authority | Source of obligation", page=90)
    context = assemble_structural_context([_hit(seed, 1)], {242: seed, 243: table})
    assert [item["chunk_id"] for item in context] == ["c242", "c243"]
    assert context[1]["reasons"] == ["following_table"]


def test_context_expansion_requires_same_section_and_page_bound():
    seed = _chunk(1, "clause", "Items:", section="A", page=1)
    wrong_section = _chunk(2, "list_item", "x", section="B", page=1)
    context = assemble_structural_context([_hit(seed, 1)], {1: seed, 2: wrong_section})
    assert [item["chunk_id"] for item in context] == ["c1"]


def test_context_expansion_is_one_hop_not_recursive():
    intro = _chunk(1, "clause", "Items:")
    child = _chunk(2, "mixed", "Child items:")
    grandchild = _chunk(3, "list_item", "Grandchild")
    config = StructuralContextConfig(max_forward_neighbors_per_seed=1)
    context = assemble_structural_context([_hit(intro, 1)], {1: intro, 2: child, 3: grandchild}, config=config)
    assert [item["chunk_id"] for item in context] == ["c1", "c2"]


def test_context_request_rejects_context_cap_smaller_than_ranked_window():
    import pytest
    from pydantic import ValidationError
    from app.schemas import ContextExpandedRetrievalRequest

    with pytest.raises(ValidationError, match="context_max_chunks"):
        ContextExpandedRetrievalRequest(
            document_id="doc",
            query="question",
            top_k=10,
            candidate_k=20,
            context_max_chunks=5,
        )


def test_context_endpoint_preserves_raw_ranking_and_adds_separate_context(monkeypatch):
    import sys
    from types import ModuleType
    from app.routers import retrieval
    from app.schemas import (
        ContextExpandedRetrievalRequest,
        RerankedRetrievalHit,
        RerankedRetrievalResponse,
    )

    seed = _chunk(242, "clause", "Report to the following authorities.", page=89)
    table = _chunk(243, "table", "Authority | Source of obligation", page=90)

    raw_hit = RerankedRetrievalHit(
        rank=1,
        reranker_score=0.99,
        hybrid_candidate_rank=1,
        fusion_score=0.03,
        dense_rrf_score=0.0,
        lexical_matched_term_count=0,
        lexical_term_coverage=0.0,
        lexical_rrf_score=0.0,
        **seed,
    )
    raw_response = RerankedRetrievalResponse(
        document_id="doc",
        query="which authorities?",
        embedding_model="BAAI/bge-m3",
        embedding_requested_device="auto",
        embedding_resolved_device="cuda",
        reranker_model="BAAI/bge-reranker-v2-m3",
        reranker_requested_device="auto",
        reranker_resolved_device="cuda",
        reranker_batch_size=2,
        reranker_max_length=1024,
        top_k=1,
        candidate_k=20,
        candidate_union_count=2,
        embedded_chunk_count=284,
        total_chunk_count=284,
        lexical_tsquery="authorities",
        hits=[raw_hit],
    )

    monkeypatch.setattr(retrieval, "hybrid_reranked_retrieval", lambda request: raw_response)
    fake_repository = ModuleType("app.db.repository")
    fake_repository.chunks_by_indices = lambda document_id, chunk_indices: {242: seed, 243: table}
    monkeypatch.setitem(sys.modules, "app.db.repository", fake_repository)

    response = retrieval.hybrid_reranked_context_retrieval(
        ContextExpandedRetrievalRequest(
            document_id="doc",
            query="which authorities?",
            top_k=1,
            candidate_k=20,
        )
    )

    assert [hit.chunk_id for hit in response.hits] == ["c242"]
    assert response.hits[0].rank == 1
    assert response.context_chunk_count == 2
    assert response.expanded_chunk_count == 1
    assert [item.chunk_id for item in response.context_chunks] == ["c242", "c243"]
    assert response.context_chunks[1].source_rank == 1
    assert response.context_chunks[1].ranked_seed_rank is None
    assert "following_table" in response.context_chunks[1].reasons
