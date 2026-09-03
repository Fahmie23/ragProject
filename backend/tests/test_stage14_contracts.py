from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.evaluation_explorer import (
    build_answer_citation_summary,
    get_answer_citation_question,
    list_answer_citation_questions,
)


def test_stage14_playground_contract_keeps_backend_as_source_of_truth():
    payload = TestClient(app).get("/api/playground/contract").json()
    assert payload["contract_version"] == "stage14_playground_contract_v1_1"
    assert payload["live_query"]["endpoint"] == "/api/generation/answer"
    assert payload["evaluation"]["read_only"] is True
    assert payload["evaluation"]["may_call_external_generation_provider"] is False
    assert all(item["frontend_calculation_allowed"] is False for item in payload["field_origins"])
    assert payload["retrieval_inspection"]["stage"] == "Stage 14.3"
    assert payload["retrieval_inspection"]["same_execution"] is True
    assert payload["retrieval_inspection"]["second_retrieval_call"] is False


def test_stage14_evaluation_summary_is_frozen_and_explains_metric_provenance():
    payload = build_answer_citation_summary()
    assert payload["dataset_id"] == "answer_citation_eval_heldout_v1"
    assert payload["split"] == "heldout"
    assert payload["benchmark_status"] == "frozen"
    assert payload["question_count"] == 18
    assert payload["answerable_question_count"] == 15
    assert payload["out_of_scope_question_count"] == 3
    assert payload["human_confirmed"] is True
    assert payload["automated_judge_used"] is False
    assert payload["external_api_calls_for_reproduction"] == 0

    metrics = {item["key"]: item for item in payload["metrics"]}
    assert metrics["answer_status_accuracy"]["value"] == 17 / 18
    assert metrics["answer_status_accuracy"]["numerator"] == 17
    assert metrics["answer_status_accuracy"]["denominator"] == 18
    assert metrics["claim_support_rate"]["numerator"] == 46
    assert metrics["claim_support_rate"]["denominator"] == 48
    assert metrics["citation_entailment_rate"]["numerator"] == 46
    assert metrics["citation_entailment_rate"]["denominator"] == 49
    assert metrics["answer_completeness"]["numerator"] == 43.5
    assert metrics["answer_completeness"]["denominator"] == 52
    assert "benchmark only" in payload["scope_statement"]


def test_stage14_question_list_exposes_failures_without_rejudging():
    rows = list_answer_citation_questions()
    assert len(rows) == 18
    by_id = {row["question_id"]: row for row in rows}
    assert "false_abstention" in by_id["ACIT-112"]["failure_flags"]
    assert by_id["ACIT-101"]["answer_completeness"] == 1.0


def test_stage14_question_detail_binds_benchmark_response_and_human_review():
    payload = get_answer_citation_question("acit-105")
    assert payload is not None
    assert payload["question_id"] == "ACIT-105"
    assert payload["read_only"] is True
    assert payload["external_api_calls"] == 0
    assert payload["benchmark"]["gold"]["required_claims"]
    assert payload["frozen_response"]["claims"]
    assert payload["frozen_response"]["evidence"]
    assert payload["semantic_review"]["claims"]
    assert payload["semantic_review"]["gold_claims"]
    assert payload["semantic_review"]["response_canonical_sha256"]


def test_stage14_evaluation_http_endpoints_are_read_only_and_filterable():
    client = TestClient(app)
    summary = client.get("/api/evaluation/answer-citation/summary")
    assert summary.status_code == 200
    assert summary.json()["external_api_calls_for_reproduction"] == 0

    failures = client.get("/api/evaluation/answer-citation/questions?failure_only=true")
    assert failures.status_code == 200
    assert failures.json()
    assert all(row["failure_flags"] for row in failures.json())

    detail = client.get("/api/evaluation/answer-citation/questions/ACIT-105")
    assert detail.status_code == 200
    assert detail.json()["read_only"] is True

    missing = client.get("/api/evaluation/answer-citation/questions/ACIT-999")
    assert missing.status_code == 404


def test_openapi_contains_stage14_contract_and_evaluation_routes():
    paths = app.openapi()["paths"]
    assert "/api/playground/contract" in paths
    assert "/api/evaluation/answer-citation/summary" in paths
    assert "/api/evaluation/answer-citation/questions" in paths
    assert "/api/evaluation/answer-citation/questions/{question_id}" in paths
