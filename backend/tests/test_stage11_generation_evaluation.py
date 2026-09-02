from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.evaluation.baseline_guard import load_manifest, validate_frozen_baseline
from app.services.evaluation.generation_metrics import (
    ANSWER_CITATION_HELDOUT_CONFIRMATION,
    aggregate_deterministic_results,
    enforce_answer_citation_split_policy,
    score_deterministic_response,
    score_required_source_groups,
    validate_response_invariants,
)


def _answered_response() -> dict:
    return {
        "status": "answered",
        "answer": "Delayed verification has conditions.",
        "cited_answer": "Delayed verification has conditions. [1]",
        "claims": [
            {
                "claim_id": "C1",
                "text": "Delayed verification has conditions.",
                "evidence_ids": ["E1"],
                "citation_ids": ["CIT-E1"],
            }
        ],
        "used_evidence_ids": ["E1"],
        "evidence": [
            {
                "evidence_id": "E1",
                "chunk_id": "chunk-102",
                "chunk_index": 102,
                "pages": [38],
                "source_element_ids": ["clause-8.1.25"],
            }
        ],
        "citations": [
            {
                "citation_id": "CIT-E1",
                "marker": "[1]",
                "evidence_id": "E1",
                "chunk_id": "chunk-102",
                "chunk_index": 102,
                "pages": [38],
                "source_element_ids": ["clause-8.1.25"],
                "validation_status": "valid",
                "locators": [
                    {
                        "kind": "clause",
                        "label": "Clause 8.1.25",
                        "pages": [38],
                        "source_element_ids": ["clause-8.1.25"],
                    }
                ],
            }
        ],
        "citation_version": "deterministic_citations_v1_2",
        "citation_validation": {
            "status": "valid",
            "citation_count": 1,
            "valid_citation_count": 1,
            "errors": [],
        },
    }


def _abstention_response() -> dict:
    return {
        "status": "insufficient_evidence",
        "answer": "The retrieved evidence is insufficient to answer this question reliably.",
        "cited_answer": "The retrieved evidence is insufficient to answer this question reliably.",
        "claims": [],
        "used_evidence_ids": [],
        "evidence": [],
        "citations": [],
        "citation_version": "deterministic_citations_v1_2",
        "citation_validation": {
            "status": "valid",
            "citation_count": 0,
            "valid_citation_count": 0,
            "errors": [],
        },
    }


def test_answered_response_invariants_are_valid():
    assert validate_response_invariants(_answered_response()) == []


def test_invariant_check_detects_citation_evidence_mismatch():
    response = _answered_response()
    response["citations"][0]["chunk_index"] = 999
    errors = validate_response_invariants(response)
    assert any("chunk provenance differs" in error for error in errors)


def test_abstention_contract_is_valid_and_scores_correctly():
    metrics = score_deterministic_response(
        response=_abstention_response(),
        expected_status="insufficient_evidence",
    )
    assert metrics["answer_status_accuracy"] == 1.0
    assert metrics["claim_citation_coverage"] == 1.0
    assert metrics["deterministic_citation_validity"] == 1.0
    assert metrics["actual_abstention"] is True


def test_required_source_group_accepts_any_matching_gold_locator():
    response = _answered_response()
    scored = score_required_source_groups(
        response=response,
        required_source_groups=[
            {
                "group_id": "G1",
                "any_of": [
                    {"kind": "clause", "label": "Clause 8.1.26", "pages": [38]},
                    {"kind": "clause", "label": "Clause 8.1.25", "pages": [38]},
                ],
            }
        ],
    )
    assert scored["required_source_coverage"] == 1.0
    assert scored["satisfied_source_groups"] == ["G1"]


def test_required_source_group_does_not_match_same_label_on_wrong_page():
    response = _answered_response()
    scored = score_required_source_groups(
        response=response,
        required_source_groups=[
            {"group_id": "G1", "any_of": [{"kind": "clause", "label": "Clause 8.1.25", "pages": [99]}]}
        ],
    )
    assert scored["required_source_coverage"] == 0.0
    assert scored["missing_source_groups"] == ["G1"]


def test_aggregate_computes_status_and_abstention_metrics():
    answered = score_deterministic_response(response=_answered_response(), expected_status="answered")
    abstain = score_deterministic_response(
        response=_abstention_response(), expected_status="insufficient_evidence"
    )
    aggregate = aggregate_deterministic_results([answered, abstain])
    assert aggregate["valid"] is True
    assert aggregate["answer_status_accuracy"] == 1.0
    assert aggregate["claim_citation_coverage"] == 1.0
    assert aggregate["deterministic_citation_validity"] == 1.0
    assert aggregate["abstention_precision"] == 1.0
    assert aggregate["abstention_recall"] == 1.0
    assert aggregate["abstention_f1"] == 1.0


def test_heldout_split_requires_frozen_benchmark_and_exact_confirmation():
    enforce_answer_citation_split_policy(split="dev", confirmation=None, benchmark_status="draft")
    with pytest.raises(ValueError, match="status='frozen'"):
        enforce_answer_citation_split_policy(
            split="heldout",
            confirmation=ANSWER_CITATION_HELDOUT_CONFIRMATION,
            benchmark_status="draft",
        )
    with pytest.raises(ValueError, match="protected"):
        enforce_answer_citation_split_policy(split="heldout", confirmation="yes", benchmark_status="frozen")
    enforce_answer_citation_split_policy(
        split="heldout",
        confirmation=ANSWER_CITATION_HELDOUT_CONFIRMATION,
        benchmark_status="frozen",
    )


def test_frozen_stage11_manifest_matches_current_pipeline():
    backend_root = Path(__file__).resolve().parents[1]
    manifest_path = backend_root / "evaluation" / "baselines" / "stage11_frozen_pipeline_manifest_v1.json"
    result = validate_frozen_baseline(backend_root=backend_root, manifest=load_manifest(manifest_path))
    assert result["valid"] is True, json.dumps(result, indent=2)
    assert result["checked_file_count"] == 7


def test_grouped_aggregates_are_based_on_outer_row_metadata():
    from app.services.evaluation.generation_metrics import grouped_deterministic_aggregates

    metrics = score_deterministic_response(response=_answered_response(), expected_status="answered")
    rows = [
        {"category": "definition", "metrics": metrics},
        {"category": "direct_requirement", "metrics": metrics},
    ]
    grouped = grouped_deterministic_aggregates(rows, field="category")
    assert set(grouped) == {"definition", "direct_requirement"}
    assert grouped["definition"]["answer_status_accuracy"] == 1.0
