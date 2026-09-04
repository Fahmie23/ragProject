from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import RetrievalExperimentConfigV1
from app.services.generation import PRODUCTION_RETRIEVAL


def test_stage15_experiment_hybrid_reranker_defaults_match_frozen_retrieval_v1() -> None:
    config = RetrievalExperimentConfigV1(strategy="hybrid_reranker")

    assert config.top_k == PRODUCTION_RETRIEVAL.top_k
    assert config.candidate_k == PRODUCTION_RETRIEVAL.candidate_k
    assert config.rrf_k == PRODUCTION_RETRIEVAL.rrf_k
    assert config.dense_weight == PRODUCTION_RETRIEVAL.dense_weight
    assert config.lexical_weight == PRODUCTION_RETRIEVAL.lexical_weight


def test_stage15_dense_strategy_keeps_hybrid_parameters_absent() -> None:
    config = RetrievalExperimentConfigV1(strategy="dense", top_k=7)

    assert config.top_k == 7
    assert config.candidate_k is None
    assert config.rrf_k is None
    assert config.dense_weight is None
    assert config.lexical_weight is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("candidate_k", 20),
        ("rrf_k", 60),
        ("dense_weight", 1.0),
        ("lexical_weight", 1.0),
    ],
)
def test_stage15_dense_strategy_rejects_hybrid_only_parameters(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match="Dense experiments must omit"):
        RetrievalExperimentConfigV1(strategy="dense", **{field: value})


def test_stage15_hybrid_requires_candidate_k_at_least_top_k() -> None:
    with pytest.raises(ValidationError, match="candidate_k must be greater than or equal to top_k"):
        RetrievalExperimentConfigV1(
            strategy="hybrid",
            top_k=21,
        )


def test_stage15_hybrid_rejects_zero_total_fusion_weight() -> None:
    with pytest.raises(ValidationError, match="At least one hybrid retrieval weight"):
        RetrievalExperimentConfigV1(
            strategy="hybrid",
            dense_weight=0.0,
            lexical_weight=0.0,
        )


def test_stage15_experiment_contract_rejects_arbitrary_model_controls() -> None:
    with pytest.raises(ValidationError):
        RetrievalExperimentConfigV1(
            strategy="hybrid_reranker",
            embedding_model="some-other-model",
        )


def test_stage15_locked_component_identities_are_canonical() -> None:
    config = RetrievalExperimentConfigV1(strategy="hybrid_reranker")
    locked = config.locked_components

    assert locked.embedding_model == "BAAI/bge-m3"
    assert locked.lexical_backend == "postgresql_fts"
    assert locked.lexical_search_config == "english"
    assert locked.lexical_ranking_method == "postgresql_fts_term_coverage_then_ts_rank_cd"
    assert locked.lexical_query_mode == "or_content_terms_v1"
    assert locked.fusion_method == "reciprocal_rank_fusion"
    assert locked.reranker_model == "BAAI/bge-reranker-v2-m3"


def test_stage15_locked_components_cannot_be_redefined() -> None:
    with pytest.raises(ValidationError):
        RetrievalExperimentConfigV1(
            strategy="hybrid_reranker",
            locked_components={
                "embedding_model": "different-model",
            },
        )


def test_stage15_config_snapshot_is_versioned_and_json_serializable() -> None:
    config = RetrievalExperimentConfigV1(
        strategy="hybrid",
        candidate_k=50,
        dense_weight=1.5,
        lexical_weight=0.5,
    )
    snapshot = config.model_dump(mode="json")

    assert snapshot["schema_version"] == "retrieval_experiment_config_v1"
    assert snapshot["strategy"] == "hybrid"
    assert snapshot["candidate_k"] == 50
    assert snapshot["dense_weight"] == 1.5
    assert snapshot["lexical_weight"] == 0.5
    assert snapshot["locked_components"]["embedding_model"] == "BAAI/bge-m3"
