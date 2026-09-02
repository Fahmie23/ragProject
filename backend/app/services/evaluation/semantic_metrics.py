"""Frozen Stage 11 semantic evaluation metrics.

This module scores only explicit human labels that conform to the frozen
``stage11_semantic_rubric_v1`` contract. It never calls an LLM and is not imported
by the production RAG runtime.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from statistics import fmean
from typing import Any, Mapping, Sequence

SEMANTIC_RUBRIC_VERSION = "stage11_semantic_rubric_v1"
CLAIM_SUPPORT_LABELS = {"supported", "partially_supported", "unsupported", "contradicted"}
CITATION_ENTAILMENT_LABELS = {"entails", "partial", "does_not_entail"}
GOLD_COVERAGE_LABELS = {"covered", "partially_covered", "missing"}
ANSWER_RELEVANCE_LABELS = {0, 1, 2}


def canonical_json_sha256(value: Any) -> str:
    """Stable SHA-256 over semantic JSON content, independent of file formatting."""

    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_frozen_rubric(rubric: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if rubric.get("schema_version") != "1.0":
        errors.append("semantic rubric schema_version must be '1.0'")
    if rubric.get("rubric_id") != SEMANTIC_RUBRIC_VERSION:
        errors.append(f"semantic rubric id must be {SEMANTIC_RUBRIC_VERSION!r}")
    if rubric.get("status") != "frozen":
        errors.append("semantic rubric status must be 'frozen'")
    expected_label_sets = {
        "claim_support": CLAIM_SUPPORT_LABELS,
        "citation_entailment": CITATION_ENTAILMENT_LABELS,
        "gold_claim_coverage": GOLD_COVERAGE_LABELS,
    }
    for dimension, expected in expected_label_sets.items():
        actual = set((rubric.get(dimension) or {}).get("labels") or [])
        if actual != expected:
            errors.append(f"semantic rubric {dimension}.labels mismatch: {sorted(actual)} != {sorted(expected)}")
    if set((rubric.get("answer_relevance") or {}).get("labels") or []) != ANSWER_RELEVANCE_LABELS:
        errors.append("semantic rubric answer_relevance.labels mismatch")
    policy = rubric.get("policy") or {}
    if policy.get("human_labels_are_authoritative_for_v1") is not True:
        errors.append("semantic rubric must declare human_labels_are_authoritative_for_v1=true")
    if policy.get("automated_judge_authorized") is not False:
        errors.append("semantic rubric v1 must keep automated_judge_authorized=false")
    if policy.get("production_pipeline_tuning_authorized") is not False:
        errors.append("semantic rubric must not authorize production pipeline tuning")
    if policy.get("retrieval_v1_remains_frozen") is not True:
        errors.append("semantic rubric must keep retrieval_v1_remains_frozen=true")
    if policy.get("citation_version") != "deterministic_citations_v1_2":
        errors.append("semantic rubric citation_version mismatch")
    return errors


def validate_semantic_calibration(
    calibration: Mapping[str, Any],
    *,
    rubric: Mapping[str, Any],
    dataset: Mapping[str, Any] | None = None,
    responses_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[str]:
    """Validate a frozen, human-labelled semantic calibration artifact.

    Optional dataset/response checks bind labels to the exact benchmark and captured
    response snapshots used during human review, preventing stale labels from being
    applied to changed model outputs.
    """

    errors = validate_frozen_rubric(rubric)
    if calibration.get("schema_version") != "1.0":
        errors.append("calibration schema_version must be '1.0'")
    if calibration.get("rubric_version") != SEMANTIC_RUBRIC_VERSION:
        errors.append(f"calibration rubric_version must be {SEMANTIC_RUBRIC_VERSION!r}")
    if calibration.get("calibration_status") != "frozen":
        errors.append("calibration_status must be 'frozen'")
    if calibration.get("human_confirmed") is not True:
        errors.append("human_confirmed must be true")
    if calibration.get("labels_prefilled") is not True:
        errors.append("labels_prefilled must be true for frozen calibration")

    if dataset is not None:
        if calibration.get("dataset_id") != dataset.get("dataset_id"):
            errors.append("calibration dataset_id does not match dataset")
        expected_dataset_hash = calibration.get("dataset_canonical_sha256")
        actual_dataset_hash = canonical_json_sha256(dataset)
        if expected_dataset_hash != actual_dataset_hash:
            errors.append(
                f"dataset canonical SHA-256 mismatch: {expected_dataset_hash!r} != {actual_dataset_hash!r}"
            )

    questions = calibration.get("questions")
    if not isinstance(questions, list) or not questions:
        errors.append("calibration questions must be a non-empty array")
        return errors

    seen_qids: set[str] = set()
    for qindex, question in enumerate(questions):
        if not isinstance(question, Mapping):
            errors.append(f"questions[{qindex}] must be an object")
            continue
        qid = str(question.get("question_id") or "")
        if not qid:
            errors.append(f"questions[{qindex}].question_id is required")
            continue
        if qid in seen_qids:
            errors.append(f"duplicate calibration question_id: {qid}")
        seen_qids.add(qid)

        if question.get("answer_relevance_score") not in ANSWER_RELEVANCE_LABELS:
            errors.append(f"{qid}.answer_relevance_score must be one of {sorted(ANSWER_RELEVANCE_LABELS)}")

        claim_ids: set[str] = set()
        for claim in question.get("claims") or []:
            claim_id = str(claim.get("claim_id") or "")
            if not claim_id:
                errors.append(f"{qid} has claim without claim_id")
                continue
            if claim_id in claim_ids:
                errors.append(f"{qid} duplicate generated claim_id: {claim_id}")
            claim_ids.add(claim_id)
            if claim.get("support_label") not in CLAIM_SUPPORT_LABELS:
                errors.append(f"{qid}.{claim_id}.support_label is invalid or blank")

        seen_relations: set[tuple[str, str]] = set()
        for relation in question.get("citation_relations") or []:
            claim_id = str(relation.get("claim_id") or "")
            citation_id = str(relation.get("citation_id") or "")
            key = (claim_id, citation_id)
            if claim_id not in claim_ids:
                errors.append(f"{qid} citation relation references unknown claim {claim_id!r}")
            if not citation_id:
                errors.append(f"{qid}.{claim_id} citation relation has blank citation_id")
            if key in seen_relations:
                errors.append(f"{qid} duplicate claim/citation relation: {claim_id}/{citation_id}")
            seen_relations.add(key)
            if relation.get("entailment_label") not in CITATION_ENTAILMENT_LABELS:
                errors.append(f"{qid}.{claim_id}/{citation_id}.entailment_label is invalid or blank")

        gold_ids: set[str] = set()
        for gold in question.get("gold_claims") or []:
            gold_id = str(gold.get("claim_id") or "")
            if not gold_id:
                errors.append(f"{qid} has gold claim without claim_id")
                continue
            if gold_id in gold_ids:
                errors.append(f"{qid} duplicate gold claim_id: {gold_id}")
            gold_ids.add(gold_id)
            if gold.get("coverage_label") not in GOLD_COVERAGE_LABELS:
                errors.append(f"{qid}.{gold_id}.coverage_label is invalid or blank")

        if responses_by_id is not None:
            response = responses_by_id.get(qid)
            if response is None:
                errors.append(f"{qid} has no response snapshot for semantic verification")
            else:
                expected_hash = question.get("response_canonical_sha256")
                actual_hash = canonical_json_sha256(response)
                if expected_hash != actual_hash:
                    errors.append(
                        f"{qid} response canonical SHA-256 mismatch: {expected_hash!r} != {actual_hash!r}"
                    )
                if question.get("actual_status") != response.get("status"):
                    errors.append(f"{qid} actual_status differs from captured response")

    return errors


def _rate(count: int, denominator: int) -> float | None:
    return count / denominator if denominator else None


def score_semantic_question(question: Mapping[str, Any]) -> dict[str, Any]:
    """Score one already-validated human-labelled semantic question."""

    claim_counts = Counter(str(item.get("support_label")) for item in question.get("claims") or [])
    relation_counts = Counter(str(item.get("entailment_label")) for item in question.get("citation_relations") or [])
    gold_counts = Counter(str(item.get("coverage_label")) for item in question.get("gold_claims") or [])

    claim_total = sum(claim_counts[label] for label in CLAIM_SUPPORT_LABELS)
    relation_total = sum(relation_counts[label] for label in CITATION_ENTAILMENT_LABELS)
    gold_total = sum(gold_counts[label] for label in GOLD_COVERAGE_LABELS)

    covered = gold_counts["covered"]
    partial_gold = gold_counts["partially_covered"]
    completeness = ((covered + 0.5 * partial_gold) / gold_total) if gold_total else None
    relevance = question.get("answer_relevance_score")

    return {
        "question_id": question.get("question_id"),
        "generated_claim_count": claim_total,
        "supported_claim_count": claim_counts["supported"],
        "partially_supported_claim_count": claim_counts["partially_supported"],
        "unsupported_claim_count": claim_counts["unsupported"],
        "contradicted_claim_count": claim_counts["contradicted"],
        "claim_support_rate": _rate(claim_counts["supported"], claim_total),
        "partial_support_rate": _rate(claim_counts["partially_supported"], claim_total),
        "unsupported_claim_rate": _rate(claim_counts["unsupported"], claim_total),
        "contradiction_rate": _rate(claim_counts["contradicted"], claim_total),
        "claim_citation_relation_count": relation_total,
        "entailed_citation_relation_count": relation_counts["entails"],
        "partial_citation_relation_count": relation_counts["partial"],
        "non_entailing_citation_relation_count": relation_counts["does_not_entail"],
        "citation_entailment_rate": _rate(relation_counts["entails"], relation_total),
        "citation_partial_rate": _rate(relation_counts["partial"], relation_total),
        "citation_non_entailment_rate": _rate(relation_counts["does_not_entail"], relation_total),
        "required_gold_claim_count": gold_total,
        "covered_gold_claim_count": covered,
        "partially_covered_gold_claim_count": partial_gold,
        "missing_gold_claim_count": gold_counts["missing"],
        "gold_claim_coverage": _rate(covered, gold_total),
        "partial_gold_claim_coverage": _rate(partial_gold, gold_total),
        "missing_gold_claim_rate": _rate(gold_counts["missing"], gold_total),
        "answer_completeness": completeness,
        "answer_relevance_score": relevance,
        "answer_relevance_normalized": (float(relevance) / 2.0) if relevance in ANSWER_RELEVANCE_LABELS else None,
    }


def aggregate_semantic_results(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Micro-average semantic labels over the human-labelled question subset."""

    if not rows:
        return {
            "semantic_question_count": 0,
            "claim_support_rate": None,
            "partial_support_rate": None,
            "unsupported_claim_rate": None,
            "contradiction_rate": None,
            "citation_entailment_rate": None,
            "citation_partial_rate": None,
            "citation_non_entailment_rate": None,
            "gold_claim_coverage": None,
            "partial_gold_claim_coverage": None,
            "missing_gold_claim_rate": None,
            "answer_completeness": None,
            "answer_relevance_mean": None,
            "answer_relevance_normalized": None,
        }

    scored = [score_semantic_question(row) for row in rows]

    claim_total = sum(row["generated_claim_count"] for row in scored)
    supported = sum(row["supported_claim_count"] for row in scored)
    partial_supported = sum(row["partially_supported_claim_count"] for row in scored)
    unsupported = sum(row["unsupported_claim_count"] for row in scored)
    contradicted = sum(row["contradicted_claim_count"] for row in scored)

    relation_total = sum(row["claim_citation_relation_count"] for row in scored)
    entails = sum(row["entailed_citation_relation_count"] for row in scored)
    partial_rel = sum(row["partial_citation_relation_count"] for row in scored)
    non_entails = sum(row["non_entailing_citation_relation_count"] for row in scored)

    gold_total = sum(row["required_gold_claim_count"] for row in scored)
    covered = sum(row["covered_gold_claim_count"] for row in scored)
    partial_gold = sum(row["partially_covered_gold_claim_count"] for row in scored)
    missing_gold = sum(row["missing_gold_claim_count"] for row in scored)

    relevance_values = [float(row["answer_relevance_score"]) for row in scored if row["answer_relevance_score"] is not None]
    relevance_mean = fmean(relevance_values) if relevance_values else None

    return {
        "semantic_question_count": len(scored),
        "generated_claim_count": claim_total,
        "supported_claim_count": supported,
        "partially_supported_claim_count": partial_supported,
        "unsupported_claim_count": unsupported,
        "contradicted_claim_count": contradicted,
        "claim_support_rate": _rate(supported, claim_total),
        "partial_support_rate": _rate(partial_supported, claim_total),
        "unsupported_claim_rate": _rate(unsupported, claim_total),
        "contradiction_rate": _rate(contradicted, claim_total),
        "claim_citation_relation_count": relation_total,
        "entailed_citation_relation_count": entails,
        "partial_citation_relation_count": partial_rel,
        "non_entailing_citation_relation_count": non_entails,
        "citation_entailment_rate": _rate(entails, relation_total),
        "citation_partial_rate": _rate(partial_rel, relation_total),
        "citation_non_entailment_rate": _rate(non_entails, relation_total),
        "required_gold_claim_count": gold_total,
        "covered_gold_claim_count": covered,
        "partially_covered_gold_claim_count": partial_gold,
        "missing_gold_claim_count": missing_gold,
        "gold_claim_coverage": _rate(covered, gold_total),
        "partial_gold_claim_coverage": _rate(partial_gold, gold_total),
        "missing_gold_claim_rate": _rate(missing_gold, gold_total),
        "answer_completeness": ((covered + 0.5 * partial_gold) / gold_total) if gold_total else None,
        "answer_relevance_mean": relevance_mean,
        "answer_relevance_normalized": (relevance_mean / 2.0) if relevance_mean is not None else None,
    }
