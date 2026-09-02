from __future__ import annotations

from typing import Any


def reciprocal_rank_fusion(
    dense_rows: list[dict[str, Any]],
    lexical_rows: list[dict[str, Any]],
    *,
    top_k: int,
    rrf_k: int = 60,
    dense_weight: float = 1.0,
    lexical_weight: float = 1.0,
) -> list[dict[str, Any]]:
    """Fuse independently ranked dense and lexical candidates with weighted RRF.

    RRF is used instead of directly mixing cosine and full-text scores because the
    two score spaces have different distributions and are not directly comparable.
    """

    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if dense_weight < 0 or lexical_weight < 0:
        raise ValueError("RRF weights cannot be negative")
    if dense_weight == 0 and lexical_weight == 0:
        raise ValueError("At least one RRF weight must be greater than zero")

    merged: dict[str, dict[str, Any]] = {}

    for rank, row in enumerate(dense_rows, start=1):
        chunk_id = str(row["chunk_id"])
        item = merged.setdefault(chunk_id, _base_item(row))
        contribution = dense_weight / (rrf_k + rank)
        item.update(
            dense_rank=rank,
            dense_score=float(row["score"]),
            dense_distance=float(row["distance"]),
            dense_rrf_score=contribution,
        )
        item["fusion_score"] += contribution

    for rank, row in enumerate(lexical_rows, start=1):
        chunk_id = str(row["chunk_id"])
        item = merged.setdefault(chunk_id, _base_item(row))
        contribution = lexical_weight / (rrf_k + rank)
        item.update(
            lexical_rank=rank,
            lexical_score=float(row["score"]),
            lexical_matched_term_count=int(row.get("matched_term_count", 0)),
            lexical_term_coverage=float(row.get("term_coverage", 0.0)),
            lexical_rrf_score=contribution,
        )
        item["fusion_score"] += contribution

    ordered = sorted(
        merged.values(),
        key=lambda item: (
            -float(item["fusion_score"]),
            _best_rank(item),
            int(item["chunk_index"]),
        ),
    )[:top_k]

    for rank, item in enumerate(ordered, start=1):
        item["rank"] = rank
    return ordered


def _base_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": 0,
        "chunk_id": row["chunk_id"],
        "chunk_index": row["chunk_index"],
        "semantic_type": row["semantic_type"],
        "fusion_score": 0.0,
        "dense_rank": None,
        "dense_score": None,
        "dense_distance": None,
        "dense_rrf_score": 0.0,
        "lexical_rank": None,
        "lexical_score": None,
        "lexical_matched_term_count": 0,
        "lexical_term_coverage": 0.0,
        "lexical_rrf_score": 0.0,
        "text": row["text"],
        "content_text": row["content_text"],
        "token_count": row["token_count"],
        "pages": list(row.get("pages", [])),
        "section_path": list(row.get("section_path", [])),
        "source_element_ids": list(row.get("source_element_ids", [])),
    }


def _best_rank(item: dict[str, Any]) -> int:
    ranks = [rank for rank in (item.get("dense_rank"), item.get("lexical_rank")) if rank is not None]
    return min(ranks) if ranks else 10**9


def rerank_candidate_union(
    dense_rows: list[dict[str, Any]],
    lexical_rows: list[dict[str, Any]],
    reranker_scores: list[float],
    *,
    top_k: int,
    rrf_k: int = 60,
    dense_weight: float = 1.0,
    lexical_weight: float = 1.0,
) -> tuple[list[dict[str, Any]], int]:
    """Rerank the deduplicated dense+lexical union with cross-encoder scores.

    RRF is retained as trace metadata and a deterministic tie-breaker, but the
    final ordering is determined by the cross-encoder score. Crucially, the
    reranker sees the *whole candidate union* rather than only the final Hybrid
    Top-K, so a relevant dense-only candidate cannot be discarded before Stage 8.
    """

    unique_count = len({str(row["chunk_id"]) for row in [*dense_rows, *lexical_rows]})
    if unique_count == 0:
        return [], 0
    if len(reranker_scores) != unique_count:
        raise ValueError(
            f"Reranker returned {len(reranker_scores)} scores for {unique_count} unique candidates."
        )

    candidates = reciprocal_rank_fusion(
        dense_rows,
        lexical_rows,
        top_k=unique_count,
        rrf_k=rrf_k,
        dense_weight=dense_weight,
        lexical_weight=lexical_weight,
    )

    for candidate, score in zip(candidates, reranker_scores, strict=True):
        candidate["hybrid_candidate_rank"] = int(candidate["rank"])
        # Preserve exactly the relevance score returned by CrossEncoder.predict().
        # It is used only for ordering and is not treated as a calibrated probability.
        candidate["reranker_score"] = float(score)

    ordered = sorted(
        candidates,
        key=lambda item: (
            -float(item["reranker_score"]),
            int(item["hybrid_candidate_rank"]),
            int(item["chunk_index"]),
        ),
    )[:top_k]

    for rank, item in enumerate(ordered, start=1):
        item["rank"] = rank
    return ordered, unique_count
