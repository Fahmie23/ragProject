from __future__ import annotations

import copy
import json
from pathlib import Path

from app.services.evaluation.semantic_metrics import (
    aggregate_semantic_results,
    canonical_json_sha256,
    score_semantic_question,
    validate_semantic_calibration,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
RUBRIC = BACKEND_ROOT / "evaluation" / "generation" / "stage11_semantic_rubric_v1.json"
CALIBRATION = BACKEND_ROOT / "evaluation" / "generation" / "answer_citation_eval_dev_calibration_v1_frozen.json"
DATASET = BACKEND_ROOT / "evaluation" / "generation" / "answer_citation_eval_dev_v1.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_frozen_semantic_contract_is_valid_without_response_binding():
    errors = validate_semantic_calibration(
        _load(CALIBRATION),
        rubric=_load(RUBRIC),
        dataset=_load(DATASET),
    )
    assert errors == []


def test_frozen_calibration_uses_nine_human_confirmed_questions():
    calibration = _load(CALIBRATION)
    assert calibration["rubric_version"] == "stage11_semantic_rubric_v1"
    assert calibration["calibration_status"] == "frozen"
    assert calibration["human_confirmed"] is True
    assert len(calibration["questions"]) == 9
    assert {q["question_id"] for q in calibration["questions"]} == {
        "ACIT-001", "ACIT-003", "ACIT-006", "ACIT-008", "ACIT-012",
        "ACIT-014", "ACIT-016", "ACIT-017", "ACIT-018",
    }


def test_frozen_semantic_aggregate_matches_confirmed_labels():
    calibration = _load(CALIBRATION)
    aggregate = aggregate_semantic_results(calibration["questions"])
    assert aggregate["semantic_question_count"] == 9
    assert aggregate["generated_claim_count"] == 20
    assert aggregate["supported_claim_count"] == 17
    assert aggregate["partially_supported_claim_count"] == 3
    assert aggregate["unsupported_claim_count"] == 0
    assert aggregate["contradicted_claim_count"] == 0
    assert aggregate["claim_support_rate"] == 17 / 20
    assert aggregate["partial_support_rate"] == 3 / 20

    assert aggregate["claim_citation_relation_count"] == 22
    assert aggregate["entailed_citation_relation_count"] == 16
    assert aggregate["partial_citation_relation_count"] == 6
    assert aggregate["non_entailing_citation_relation_count"] == 0
    assert aggregate["citation_entailment_rate"] == 16 / 22

    assert aggregate["required_gold_claim_count"] == 24
    assert aggregate["covered_gold_claim_count"] == 20
    assert aggregate["partially_covered_gold_claim_count"] == 2
    assert aggregate["missing_gold_claim_count"] == 2
    assert aggregate["gold_claim_coverage"] == 20 / 24
    assert aggregate["answer_completeness"] == 21 / 24
    assert aggregate["answer_relevance_mean"] == 17 / 9
    assert aggregate["answer_relevance_normalized"] == 17 / 18


def test_compound_claim_can_be_supported_with_individually_partial_citations():
    calibration = _load(CALIBRATION)
    q = next(q for q in calibration["questions"] if q["question_id"] == "ACIT-012")
    c3 = next(c for c in q["claims"] if c["claim_id"] == "C3")
    c3_relations = [r for r in q["citation_relations"] if r["claim_id"] == "C3"]
    assert c3["support_label"] == "supported"
    assert [r["entailment_label"] for r in c3_relations] == ["partial", "partial"]


def test_abstention_does_not_create_synthetic_semantic_units():
    calibration = _load(CALIBRATION)
    q = next(q for q in calibration["questions"] if q["question_id"] == "ACIT-018")
    metrics = score_semantic_question(q)
    assert metrics["generated_claim_count"] == 0
    assert metrics["claim_support_rate"] is None
    assert metrics["citation_entailment_rate"] is None
    assert metrics["gold_claim_coverage"] is None
    assert metrics["answer_completeness"] is None
    assert metrics["answer_relevance_score"] == 2


def test_invalid_or_blank_semantic_label_is_rejected():
    calibration = _load(CALIBRATION)
    broken = copy.deepcopy(calibration)
    broken["questions"][0]["claims"][0]["support_label"] = None
    errors = validate_semantic_calibration(broken, rubric=_load(RUBRIC), dataset=_load(DATASET))
    assert any("support_label is invalid or blank" in error for error in errors)


def test_dataset_hash_prevents_labels_from_scoring_a_changed_benchmark():
    calibration = _load(CALIBRATION)
    changed_dataset = copy.deepcopy(_load(DATASET))
    changed_dataset["questions"][0]["question"] += " changed"
    errors = validate_semantic_calibration(calibration, rubric=_load(RUBRIC), dataset=changed_dataset)
    assert any("dataset canonical SHA-256 mismatch" in error for error in errors)


def test_response_hash_prevents_stale_labels_from_scoring_changed_output():
    calibration = _load(CALIBRATION)
    q = calibration["questions"][0]
    response = {"status": q["actual_status"], "answer": "different output"}
    q["response_canonical_sha256"] = canonical_json_sha256({"status": q["actual_status"], "answer": "original"})
    errors = validate_semantic_calibration(
        calibration,
        rubric=_load(RUBRIC),
        dataset=_load(DATASET),
        responses_by_id={item["question_id"]: (response if item["question_id"] == q["question_id"] else {}) for item in calibration["questions"]},
    )
    assert any(f"{q['question_id']} response canonical SHA-256 mismatch" in error for error in errors)


def test_frozen_semantic_evaluation_manifest_matches_contract_files():
    from app.services.evaluation.baseline_guard import load_manifest, validate_frozen_baseline

    manifest = BACKEND_ROOT / "evaluation" / "baselines" / "stage11_semantic_evaluation_manifest_v1.json"
    result = validate_frozen_baseline(backend_root=BACKEND_ROOT, manifest=load_manifest(manifest))
    assert result["valid"] is True, json.dumps(result, indent=2)
    assert result["checked_file_count"] == 3
