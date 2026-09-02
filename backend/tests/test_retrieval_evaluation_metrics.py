from __future__ import annotations

import pytest

from app.services.evaluation.retrieval_metrics import (
    HELDOUT_CONFIRMATION,
    aggregate_scored_results,
    enforce_split_policy,
    score_context_assembly,
    score_ranking,
)


def test_score_ranking_single_primary():
    metrics = score_ranking(
        retrieved_chunk_ids=["x", "gold", "y"],
        primary_chunk_ids=["gold"],
        required_evidence_groups=[["gold"]],
        ks=[1, 3, 5],
    )
    assert metrics["first_relevant_rank"] == 2
    assert metrics["reciprocal_rank"] == pytest.approx(0.5)
    assert metrics["hit_at_1"] == 0.0
    assert metrics["hit_at_3"] == 1.0
    assert metrics["recall_at_3"] == 1.0
    assert metrics["complete_evidence_at_3"] == 1.0


def test_multi_evidence_recall_and_complete_evidence_are_distinct():
    metrics = score_ranking(
        retrieved_chunk_ids=["a", "noise", "b"],
        primary_chunk_ids=["a", "b", "c"],
        required_evidence_groups=[["a"], ["b"], ["c"]],
        ks=[1, 3, 5],
    )
    assert metrics["hit_at_1"] == 1.0
    assert metrics["recall_at_1"] == pytest.approx(1 / 3)
    assert metrics["recall_at_3"] == pytest.approx(2 / 3)
    assert metrics["complete_evidence_at_3"] == 0.0
    assert metrics["complete_evidence_at_5"] == 0.0


def test_aggregate_marks_any_failed_question_invalid():
    ok = {
        "status": "ok",
        "metrics": score_ranking(
            retrieved_chunk_ids=["gold"],
            primary_chunk_ids=["gold"],
            required_evidence_groups=[["gold"]],
            ks=[1, 3, 5],
        ),
    }
    failed = {"status": "error", "metrics": {}}
    aggregate = aggregate_scored_results([ok, failed], ks=[1, 3, 5])
    assert aggregate["valid"] is False
    assert aggregate["successful_question_count"] == 1
    assert aggregate["failed_question_count"] == 1
    assert aggregate["hit_at_1"] == 1.0


def test_heldout_requires_frozen_config_and_exact_confirmation():
    enforce_split_policy(split="dev", confirmation=None, config_status="draft")

    with pytest.raises(ValueError, match="status='frozen'"):
        enforce_split_policy(
            split="heldout",
            confirmation=HELDOUT_CONFIRMATION,
            config_status="draft",
        )

    with pytest.raises(ValueError, match="protected"):
        enforce_split_policy(
            split="heldout",
            confirmation="yes",
            config_status="frozen",
        )

    enforce_split_policy(
        split="heldout",
        confirmation=HELDOUT_CONFIRMATION,
        config_status="frozen",
    )


def test_context_metrics_use_source_rank_without_changing_retrieval_rank_metrics():
    context = [
        {"chunk_id": "lead", "source_rank": 1},
        {"chunk_id": "table", "source_rank": 1},
        {"chunk_id": "other", "source_rank": 3},
    ]
    scored = score_context_assembly(
        context_chunks=context,
        primary_chunk_ids=["lead", "table"],
        required_evidence_groups=[["lead"], ["table"]],
        ks=[1, 3],
    )
    assert scored["context_recall_at_1"] == 1.0
    assert scored["context_complete_evidence_at_1"] == 1.0
    assert scored["context_chunk_count_at_1"] == 2
    assert scored["context_chunk_count_at_3"] == 3

