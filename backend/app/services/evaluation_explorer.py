from __future__ import annotations

import json
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[2]
EVALUATION_ROOT = BACKEND_ROOT / "evaluation"

DATASET_PATH = EVALUATION_ROOT / "generation" / "answer_citation_eval_heldout_v1.json"
CALIBRATION_PATH = EVALUATION_ROOT / "generation" / "answer_citation_eval_heldout_calibration_v1_frozen.json"
DETERMINISTIC_AGGREGATE_PATH = (
    EVALUATION_ROOT / "reports" / "stage11_3c_heldout_score_v1" / "heldout_aggregate_metrics.json"
)
SEMANTIC_AGGREGATE_PATH = (
    EVALUATION_ROOT / "reports" / "stage11_3c_heldout_score_v1" / "heldout_semantic_aggregate_metrics.json"
)
DETERMINISTIC_RESULTS_PATH = (
    EVALUATION_ROOT / "reports" / "stage11_3c_heldout_score_v1" / "heldout_deterministic_results.json"
)
RESPONSE_DIR = EVALUATION_ROOT / "reports" / "stage11_3_heldout_capture_v1" / "responses"
FINAL_MANIFEST_PATH = EVALUATION_ROOT / "baselines" / "stage11_final_evaluation_manifest_v1.json"


class EvaluationExplorerError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise EvaluationExplorerError(f"Required frozen evaluation artifact is missing: {path.relative_to(BACKEND_ROOT)}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationExplorerError(f"Could not read frozen evaluation artifact: {path.relative_to(BACKEND_ROOT)}") from exc
    if not isinstance(payload, dict):
        raise EvaluationExplorerError(f"Frozen evaluation artifact must be a JSON object: {path.relative_to(BACKEND_ROOT)}")
    return payload


def _artifact_id(path: Path) -> str:
    return str(path.relative_to(BACKEND_ROOT)).replace("\\", "/")


def _format_percent(value: float | None) -> str | None:
    return None if value is None else f"{value * 100:.2f}%"


def _benchmark_source_filename(dataset: dict[str, Any]) -> str | None:
    """Resolve a human-readable source filename from frozen response snapshots only."""
    for question in dataset.get("questions") or []:
        question_id = str((question or {}).get("question_id") or "").strip()
        if not question_id:
            continue
        response_path = RESPONSE_DIR / f"{question_id}.json"
        if not response_path.exists():
            continue
        response = _load_json(response_path)
        for citation in response.get("citations") or []:
            if isinstance(citation, dict) and citation.get("source_filename"):
                return str(citation["source_filename"])
    return None


def _question_results_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = payload.get("results") or []
    return {
        str(row.get("question_id")): row
        for row in rows
        if isinstance(row, dict) and row.get("question_id")
    }


def _questions_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = payload.get("questions") or []
    return {
        str(row.get("question_id")): row
        for row in rows
        if isinstance(row, dict) and row.get("question_id")
    }


def build_answer_citation_summary() -> dict[str, Any]:
    dataset = _load_json(DATASET_PATH)
    calibration = _load_json(CALIBRATION_PATH)
    deterministic = _load_json(DETERMINISTIC_AGGREGATE_PATH)
    semantic = _load_json(SEMANTIC_AGGREGATE_PATH)
    deterministic_results = _load_json(DETERMINISTIC_RESULTS_PATH)
    manifest = _load_json(FINAL_MANIFEST_PATH)

    rows = list(deterministic_results.get("results") or [])
    status_correct = sum(
        1
        for row in rows
        if isinstance(row, dict) and float((row.get("metrics") or {}).get("answer_status_accuracy", 0.0)) == 1.0
    )
    deterministic_valid = sum(
        1
        for row in rows
        if isinstance(row, dict)
        and float((row.get("metrics") or {}).get("deterministic_citation_validity", 0.0)) == 1.0
    )
    required_source_question_count = sum(
        1
        for row in rows
        if isinstance(row, dict) and (row.get("metrics") or {}).get("required_source_coverage") is not None
    )
    relevance_total = sum(
        int((row.get("semantic_metrics") or {}).get("answer_relevance_score", 0))
        for row in rows
        if isinstance(row, dict) and row.get("semantic_metrics")
    )

    metrics = [
        {
            "key": "answer_status_accuracy",
            "display_name": "Answer Status Accuracy",
            "value": deterministic.get("answer_status_accuracy"),
            "display_value": _format_percent(deterministic.get("answer_status_accuracy")),
            "numerator": float(status_correct),
            "denominator": float(len(rows)),
            "formula": "questions with actual status equal to expected status / held-out questions",
            "scope": "deterministic",
            "source_artifact": _artifact_id(DETERMINISTIC_AGGREGATE_PATH),
            "notes": "Measures answered vs insufficient_evidence status only; it is not semantic answer correctness.",
        },
        {
            "key": "abstention_precision",
            "display_name": "Abstention Precision",
            "value": deterministic.get("abstention_precision"),
            "display_value": _format_percent(deterministic.get("abstention_precision")),
            "numerator": float(deterministic.get("abstention_true_positive", 0)),
            "denominator": float(deterministic.get("abstention_true_positive", 0))
            + float(deterministic.get("abstention_false_positive", 0)),
            "formula": "correct abstentions / all system abstentions",
            "scope": "deterministic",
            "source_artifact": _artifact_id(DETERMINISTIC_AGGREGATE_PATH),
            "notes": "Among questions the system abstained on, measures how often abstention was expected.",
        },
        {
            "key": "abstention_recall",
            "display_name": "Abstention Recall",
            "value": deterministic.get("abstention_recall"),
            "display_value": _format_percent(deterministic.get("abstention_recall")),
            "numerator": float(deterministic.get("abstention_true_positive", 0)),
            "denominator": float(deterministic.get("abstention_true_positive", 0))
            + float(deterministic.get("abstention_false_negative", 0)),
            "formula": "correct abstentions / benchmark questions that should abstain",
            "scope": "deterministic",
            "source_artifact": _artifact_id(DETERMINISTIC_AGGREGATE_PATH),
            "notes": "Measures whether out-of-scope benchmark questions are actually refused instead of answered.",
        },
        {
            "key": "abstention_f1",
            "display_name": "Abstention F1",
            "value": deterministic.get("abstention_f1"),
            "display_value": _format_percent(deterministic.get("abstention_f1")),
            "numerator": None,
            "denominator": None,
            "formula": "harmonic mean of abstention precision and abstention recall",
            "scope": "deterministic",
            "source_artifact": _artifact_id(DETERMINISTIC_AGGREGATE_PATH),
            "notes": "Balances false abstentions against failures to abstain on questions outside the document evidence.",
        },
        {
            "key": "claim_citation_coverage",
            "display_name": "Claim Citation Coverage",
            "value": deterministic.get("claim_citation_coverage"),
            "display_value": _format_percent(deterministic.get("claim_citation_coverage")),
            "numerator": None,
            "denominator": float(len(rows)),
            "formula": "macro mean of per-question cited-claim coverage; valid abstentions with zero claims score 1.0",
            "scope": "deterministic",
            "source_artifact": _artifact_id(DETERMINISTIC_AGGREGATE_PATH),
            "notes": "Checks citation presence on generated claims, not semantic entailment.",
        },
        {
            "key": "deterministic_citation_validity",
            "display_name": "Deterministic Citation Validity",
            "value": deterministic.get("deterministic_citation_validity"),
            "display_value": _format_percent(deterministic.get("deterministic_citation_validity")),
            "numerator": float(deterministic_valid),
            "denominator": float(len(rows)),
            "formula": "questions with zero deterministic citation/provenance invariant errors / held-out questions",
            "scope": "deterministic",
            "source_artifact": _artifact_id(DETERMINISTIC_AGGREGATE_PATH),
            "notes": "Validates provenance structure and mapping; it does not judge whether a citation semantically entails a claim.",
        },
        {
            "key": "required_source_coverage",
            "display_name": "Required Source Coverage",
            "value": deterministic.get("required_source_coverage"),
            "display_value": _format_percent(deterministic.get("required_source_coverage")),
            "numerator": None,
            "denominator": float(required_source_question_count),
            "formula": "macro mean of required-source-group coverage across questions that define required source groups",
            "scope": "deterministic",
            "source_artifact": _artifact_id(DETERMINISTIC_AGGREGATE_PATH),
            "notes": "Measures whether validated citations hit benchmark-required structural sources.",
        },
        {
            "key": "claim_support_rate",
            "display_name": "Claim Support Rate",
            "value": semantic.get("claim_support_rate"),
            "display_value": _format_percent(semantic.get("claim_support_rate")),
            "numerator": float(semantic.get("supported_claim_count", 0)),
            "denominator": float(semantic.get("generated_claim_count", 0)),
            "formula": "fully supported generated claims / generated claims",
            "scope": "human_frozen_rubric",
            "source_artifact": _artifact_id(SEMANTIC_AGGREGATE_PATH),
            "notes": "Labels are from the frozen human semantic calibration; no automated judge is used.",
        },
        {
            "key": "citation_entailment_rate",
            "display_name": "Citation Entailment Rate",
            "value": semantic.get("citation_entailment_rate"),
            "display_value": _format_percent(semantic.get("citation_entailment_rate")),
            "numerator": float(semantic.get("entailed_citation_relation_count", 0)),
            "denominator": float(semantic.get("claim_citation_relation_count", 0)),
            "formula": "claim-citation relations labeled entails / reviewed claim-citation relations",
            "scope": "human_frozen_rubric",
            "source_artifact": _artifact_id(SEMANTIC_AGGREGATE_PATH),
            "notes": "Evaluates semantic support of each individual citation relation.",
        },
        {
            "key": "answer_completeness",
            "display_name": "Answer Completeness",
            "value": semantic.get("answer_completeness"),
            "display_value": _format_percent(semantic.get("answer_completeness")),
            "numerator": float(semantic.get("covered_gold_claim_count", 0))
            + 0.5 * float(semantic.get("partially_covered_gold_claim_count", 0)),
            "denominator": float(semantic.get("required_gold_claim_count", 0)),
            "formula": "(covered gold requirements + 0.5 × partially covered gold requirements) / required gold requirements",
            "scope": "human_frozen_rubric",
            "source_artifact": _artifact_id(SEMANTIC_AGGREGATE_PATH),
            "notes": "Missing gold requirements contribute 0.0; this metric is benchmark-specific.",
        },
        {
            "key": "answer_relevance_mean",
            "display_name": "Answer Relevance",
            "value": semantic.get("answer_relevance_mean"),
            "display_value": f"{float(semantic.get('answer_relevance_mean', 0.0)):.2f} / 2",
            "numerator": float(relevance_total),
            "denominator": float(len(rows)),
            "formula": "sum of frozen human relevance scores / reviewed held-out questions; score range 0–2",
            "scope": "human_frozen_rubric",
            "source_artifact": _artifact_id(SEMANTIC_AGGREGATE_PATH),
            "notes": "0=poor, 1=acceptable/materially incomplete, 2=strong according to the frozen rubric.",
        },
    ]

    counts = dataset.get("counts") or {}
    document = dataset.get("document") or {}
    return {
        "evaluation_id": "stage11_answer_citation_heldout_v1_final",
        "dataset_id": dataset.get("dataset_id"),
        "split": "heldout",
        "benchmark_status": dataset.get("benchmark_status"),
        "question_count": int(counts.get("questions", 0)),
        "answerable_question_count": int(counts.get("answered", 0)),
        "out_of_scope_question_count": int(counts.get("insufficient_evidence", 0)),
        "document_id": document.get("document_id"),
        "source_filename": _benchmark_source_filename(dataset),
        "pdf_page_count": int(document.get("pdf_page_count", 0) or 0),
        "source_sha256": document.get("source_sha256"),
        "evaluation_type": "frozen_offline_benchmark",
        "heldout_tuning_authorized": bool(manifest.get("heldout_tuning_authorized", False)),
        "production_pipeline_modified_for_heldout": bool(manifest.get("production_pipeline_modified_for_heldout", False)),
        "retrieval_profile": (dataset.get("policy") or {}).get("retrieval_profile"),
        "citation_version": (dataset.get("policy") or {}).get("citation_version"),
        "rubric_version": calibration.get("rubric_version"),
        "human_confirmed": bool(calibration.get("human_confirmed")),
        "automated_judge_used": bool(calibration.get("automated_judge_used")),
        "external_api_calls_for_reproduction": 0,
        "scope_statement": (
            "These values describe performance on the frozen answer_citation_eval_heldout_v1 benchmark only; "
            "they are not universal performance guarantees for arbitrary PDFs or domains."
        ),
        "metrics": metrics,
        "artifacts": {
            "dataset": _artifact_id(DATASET_PATH),
            "semantic_calibration": _artifact_id(CALIBRATION_PATH),
            "deterministic_aggregate": _artifact_id(DETERMINISTIC_AGGREGATE_PATH),
            "semantic_aggregate": _artifact_id(SEMANTIC_AGGREGATE_PATH),
            "deterministic_results": _artifact_id(DETERMINISTIC_RESULTS_PATH),
            "final_manifest": _artifact_id(FINAL_MANIFEST_PATH),
        },
        "manifest": {
            "baseline_id": manifest.get("baseline_id") or manifest.get("evaluation_id"),
            "valid": manifest.get("valid", True),
        },
    }


def list_answer_citation_questions() -> list[dict[str, Any]]:
    dataset = _load_json(DATASET_PATH)
    deterministic = _load_json(DETERMINISTIC_RESULTS_PATH)
    calibration = _load_json(CALIBRATION_PATH)
    det_by_id = _question_results_map(deterministic)
    cal_by_id = _questions_map(calibration)

    result: list[dict[str, Any]] = []
    for question in dataset.get("questions") or []:
        question_id = str(question.get("question_id"))
        det = det_by_id.get(question_id, {})
        metrics = det.get("metrics") or {}
        semantic = det.get("semantic_metrics") or {}
        calibration_row = cal_by_id.get(question_id, {})
        actual_status = metrics.get("actual_status") or calibration_row.get("actual_status")
        expected_status = question.get("expected_status")
        flags: list[str] = []
        if expected_status == "answered" and actual_status == "insufficient_evidence":
            flags.append("false_abstention")
        if int(semantic.get("missing_gold_claim_count", 0) or 0) > 0:
            flags.append("missing_gold_requirements")
        source_coverage = metrics.get("required_source_coverage")
        if source_coverage is not None and float(source_coverage) < 1.0:
            flags.append("required_source_gap")
        if int(semantic.get("unsupported_claim_count", 0) or 0) > 0:
            flags.append("unsupported_claim")
        if int(semantic.get("contradicted_claim_count", 0) or 0) > 0:
            flags.append("contradicted_claim")

        result.append(
            {
                "question_id": question_id,
                "category": question.get("category"),
                "difficulty": question.get("difficulty"),
                "question": question.get("question"),
                "expected_status": expected_status,
                "actual_status": actual_status,
                "answer_status_correct": metrics.get("answer_status_accuracy") == 1.0,
                "deterministic_citation_validity": metrics.get("deterministic_citation_validity"),
                "claim_support_rate": semantic.get("claim_support_rate"),
                "citation_entailment_rate": semantic.get("citation_entailment_rate"),
                "answer_completeness": semantic.get("answer_completeness"),
                "answer_relevance_score": semantic.get("answer_relevance_score"),
                "required_source_coverage": source_coverage,
                "failure_flags": flags,
            }
        )
    return result


def get_answer_citation_question(question_id: str) -> dict[str, Any] | None:
    normalized = question_id.strip().upper()
    dataset = _load_json(DATASET_PATH)
    deterministic = _load_json(DETERMINISTIC_RESULTS_PATH)
    calibration = _load_json(CALIBRATION_PATH)

    benchmark = _questions_map(dataset).get(normalized)
    deterministic_row = _question_results_map(deterministic).get(normalized)
    semantic_row = _questions_map(calibration).get(normalized)
    if benchmark is None or deterministic_row is None or semantic_row is None:
        return None

    response_path = RESPONSE_DIR / f"{normalized}.json"
    response = _load_json(response_path)
    return {
        "question_id": normalized,
        "benchmark": benchmark,
        "deterministic_result": deterministic_row,
        "semantic_review": {
            "rubric_version": calibration.get("rubric_version"),
            "human_confirmed": calibration.get("human_confirmed"),
            "automated_judge_used": calibration.get("automated_judge_used"),
            "claims": semantic_row.get("claims") or [],
            "citation_relations": semantic_row.get("citation_relations") or [],
            "gold_claims": semantic_row.get("gold_claims") or [],
            "answer_relevance_score": semantic_row.get("answer_relevance_score"),
            "answer_relevance_notes": semantic_row.get("answer_relevance_notes"),
            "reviewer_notes": semantic_row.get("reviewer_notes"),
            "response_canonical_sha256": semantic_row.get("response_canonical_sha256"),
        },
        "frozen_response": response,
        "artifacts": {
            "dataset": _artifact_id(DATASET_PATH),
            "semantic_calibration": _artifact_id(CALIBRATION_PATH),
            "deterministic_results": _artifact_id(DETERMINISTIC_RESULTS_PATH),
            "response_snapshot": _artifact_id(response_path),
        },
        "read_only": True,
        "external_api_calls": 0,
    }
