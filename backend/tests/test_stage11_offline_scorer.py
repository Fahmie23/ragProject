from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCORER = BACKEND_ROOT / "scripts" / "score_answer_citation_results.py"
TEMPLATE = BACKEND_ROOT / "evaluation" / "generation" / "answer_citation_eval_dev_template_v1.json"


def _response() -> dict:
    return {
        "status": "answered",
        "answer": "Supported.",
        "cited_answer": "Supported. [1]",
        "claims": [{"claim_id": "C1", "text": "Supported.", "evidence_ids": ["E1"], "citation_ids": ["CIT-E1"]}],
        "used_evidence_ids": ["E1"],
        "evidence": [{"evidence_id": "E1", "chunk_id": "c1", "chunk_index": 1, "pages": [1], "source_element_ids": ["s1"]}],
        "citations": [{
            "citation_id": "CIT-E1",
            "marker": "[1]",
            "evidence_id": "E1",
            "chunk_id": "c1",
            "chunk_index": 1,
            "pages": [1],
            "source_element_ids": ["s1"],
            "validation_status": "valid",
            "locators": [{"kind": "clause", "label": "REPLACE_WITH_CLAUSE_LABEL", "pages": [1], "source_element_ids": ["s1"]}],
        }],
        "citation_version": "deterministic_citations_v1_2",
        "citation_validation": {"status": "valid", "citation_count": 1, "valid_citation_count": 1, "errors": []},
    }


def test_offline_scorer_scores_dev_fixture(tmp_path: Path):
    responses = tmp_path / "responses"
    responses.mkdir()
    (responses / "ACIT-001.json").write_text(json.dumps(_response()), encoding="utf-8")
    output = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            str(SCORER),
            "--dataset", str(TEMPLATE),
            "--responses-dir", str(responses),
            "--split", "dev",
            "--output-dir", str(output),
        ],
        cwd=BACKEND_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    aggregate = json.loads((output / "dev_aggregate_metrics.json").read_text(encoding="utf-8"))
    assert aggregate["answer_status_accuracy"] == 1.0
    assert aggregate["claim_citation_coverage"] == 1.0
    assert aggregate["deterministic_citation_validity"] == 1.0
    assert aggregate["required_source_coverage"] == 1.0
    assert aggregate["semantic_metrics_status"] == "not_scored"


def test_offline_scorer_refuses_heldout_on_draft_benchmark(tmp_path: Path):
    result = subprocess.run(
        [
            sys.executable,
            str(SCORER),
            "--dataset", str(TEMPLATE),
            "--responses-dir", str(tmp_path),
            "--split", "heldout",
        ],
        cwd=BACKEND_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "requires benchmark status='frozen'" in (result.stdout + result.stderr)


def test_offline_scorer_scores_frozen_human_semantic_labels(tmp_path: Path):
    from app.services.evaluation.semantic_metrics import canonical_json_sha256

    dataset = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    response = _response()
    responses = tmp_path / "responses"
    responses.mkdir()
    (responses / "ACIT-001.json").write_text(json.dumps(response), encoding="utf-8")

    calibration = {
        "schema_version": "1.0",
        "calibration_id": "synthetic_frozen_calibration",
        "dataset_id": dataset["dataset_id"],
        "dataset_canonical_sha256": canonical_json_sha256(dataset),
        "rubric_version": "stage11_semantic_rubric_v1",
        "calibration_status": "frozen",
        "human_confirmed": True,
        "labels_prefilled": True,
        "questions": [
            {
                "question_id": "ACIT-001",
                "actual_status": "answered",
                "response_canonical_sha256": canonical_json_sha256(response),
                "claims": [{"claim_id": "C1", "support_label": "supported"}],
                "citation_relations": [
                    {"claim_id": "C1", "citation_id": "CIT-E1", "entailment_label": "entails"}
                ],
                "gold_claims": [{"claim_id": "GC1", "coverage_label": "covered"}],
                "answer_relevance_score": 2,
            }
        ],
    }
    calibration_path = tmp_path / "calibration.json"
    calibration_path.write_text(json.dumps(calibration), encoding="utf-8")
    output = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            str(SCORER),
            "--dataset", str(TEMPLATE),
            "--responses-dir", str(responses),
            "--split", "dev",
            "--semantic-calibration", str(calibration_path),
            "--output-dir", str(output),
        ],
        cwd=BACKEND_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    semantic = json.loads((output / "dev_semantic_aggregate_metrics.json").read_text(encoding="utf-8"))
    assert semantic["semantic_question_count"] == 1
    assert semantic["claim_support_rate"] == 1.0
    assert semantic["citation_entailment_rate"] == 1.0
    assert semantic["gold_claim_coverage"] == 1.0
    assert semantic["answer_completeness"] == 1.0
    aggregate = json.loads((output / "dev_aggregate_metrics.json").read_text(encoding="utf-8"))
    assert aggregate["semantic_metrics_status"] == "scored_human_frozen_rubric"


def test_offline_scorer_refuses_tampered_frozen_heldout_dataset(tmp_path: Path):
    dataset_path = BACKEND_ROOT / "evaluation" / "generation" / "answer_citation_eval_heldout_v1.json"
    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    data["questions"][0]["question"] += " "
    tampered = tmp_path / "tampered_heldout.json"
    tampered.write_text(json.dumps(data, indent=2), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCORER),
            "--dataset", str(tampered),
            "--responses-dir", str(tmp_path / "responses"),
            "--split", "heldout",
            "--confirm-heldout", "RUN_FROZEN_ANSWER_CITATION_HELDOUT_V1",
        ],
        cwd=BACKEND_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 5
    assert "held-out benchmark validation failed" in result.stdout
    assert "executed dataset hash mismatch" in result.stdout
