from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATASET = BACKEND_ROOT / "evaluation" / "generation" / "answer_citation_eval_dev_v1.json"
VALIDATOR = BACKEND_ROOT / "scripts" / "validate_answer_citation_eval_dataset.py"
SOURCE_VALIDATOR = BACKEND_ROOT / "scripts" / "validate_answer_citation_eval_source.py"
OVERLAP_AUDIT = BACKEND_ROOT / "scripts" / "audit_stage11_dev_question_overlap.py"
SCORER = BACKEND_ROOT / "scripts" / "score_answer_citation_results.py"
CALIBRATION = BACKEND_ROOT / "scripts" / "prepare_stage11_semantic_calibration.py"
SELECTION = BACKEND_ROOT / "evaluation" / "generation" / "answer_citation_eval_dev_calibration_v1.json"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, *args], cwd=BACKEND_ROOT, text=True, capture_output=True, check=False)


def _abstention_response(question: str) -> dict:
    answer = "The retrieved evidence is insufficient to answer this question reliably."
    return {
        "document_id": "485c4989-c300-45c8-ac06-79a59492bb5c",
        "question": question,
        "status": "insufficient_evidence",
        "answer": answer,
        "cited_answer": answer,
        "claims": [],
        "used_evidence_ids": [],
        "evidence": [],
        "citations": [],
        "citation_version": "deterministic_citations_v1_2",
        "citation_validation": {"status": "valid", "citation_count": 0, "valid_citation_count": 0, "errors": []},
    }


def _synthetic_answered_response(question: dict) -> dict:
    groups = question["gold"]["required_source_groups"]
    evidence = []
    citations = []
    evidence_ids = []
    citation_ids = []
    markers = []
    for index, group in enumerate(groups, start=1):
        locator = group["any_of"][0]
        eid = f"E{index}"
        cid = f"CIT-{eid}"
        source_id = f"synthetic-source-{index}"
        pages = list(locator.get("pages") or [1])
        evidence.append({
            "evidence_id": eid,
            "chunk_id": f"synthetic-chunk-{index}",
            "chunk_index": index,
            "pages": pages,
            "source_element_ids": [source_id],
        })
        citations.append({
            "citation_id": cid,
            "marker": f"[{index}]",
            "evidence_id": eid,
            "chunk_id": f"synthetic-chunk-{index}",
            "chunk_index": index,
            "pages": pages,
            "source_element_ids": [source_id],
            "validation_status": "valid",
            "locators": [{**locator, "source_element_ids": [source_id]}],
        })
        evidence_ids.append(eid)
        citation_ids.append(cid)
        markers.append(f"[{index}]")

    gold_claims = question["gold"]["required_claims"]
    claims = []
    for index, gold in enumerate(gold_claims, start=1):
        slot = (index - 1) % len(evidence_ids)
        claims.append({
            "claim_id": f"C{index}",
            "text": f"Synthetic response for {gold['claim_id']}.",
            "evidence_ids": [evidence_ids[slot]],
            "citation_ids": [citation_ids[slot]],
        })
    cited = " ".join(f"{claim['text']} {citations[(i-1) % len(citations)]['marker']}" for i, claim in enumerate(claims, start=1))
    return {
        "document_id": "485c4989-c300-45c8-ac06-79a59492bb5c",
        "question": question["question"],
        "status": "answered",
        "answer": " ".join(claim["text"] for claim in claims),
        "cited_answer": cited,
        "claims": claims,
        "used_evidence_ids": list(dict.fromkeys(eid for claim in claims for eid in claim["evidence_ids"])),
        "evidence": evidence,
        "citations": citations,
        "citation_version": "deterministic_citations_v1_2",
        "citation_validation": {"status": "valid", "citation_count": len(citations), "valid_citation_count": len(citations), "errors": []},
    }


def _write_synthetic_responses(directory: Path) -> None:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    directory.mkdir(parents=True, exist_ok=True)
    for q in dataset["questions"]:
        response = _abstention_response(q["question"]) if q["expected_status"] == "insufficient_evidence" else _synthetic_answered_response(q)
        (directory / f"{q['question_id']}.json").write_text(json.dumps(response), encoding="utf-8")


def test_stage11_dev_dataset_has_intended_shape_and_validates():
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    assert data["dataset_id"] == "answer_citation_eval_dev_v1"
    assert data["benchmark_status"] == "draft"
    assert data["counts"] == {"questions": 20, "dev": 20, "heldout": 0, "answered": 17, "insufficient_evidence": 3}
    assert all(q["split"] == "dev" for q in data["questions"])
    assert len({q["question_id"] for q in data["questions"]}) == 20
    result = _run(str(VALIDATOR), str(DATASET))
    assert result.returncode == 0, result.stdout + result.stderr


def test_stage11_dev_gold_locators_resolve_against_frozen_canonical_source():
    result = _run(str(SOURCE_VALIDATOR), str(DATASET))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Gold locators checked: 34" in result.stdout


def test_source_validator_rejects_wrong_gold_page(tmp_path: Path):
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    data["questions"][1]["gold"]["required_source_groups"][0]["any_of"][0]["pages"] = [99]
    path = tmp_path / "wrong_page.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = _run(str(SOURCE_VALIDATOR), str(path))
    assert result.returncode == 1
    assert "not supported by canonical pages" in result.stdout


def test_stage11_dev_questions_do_not_duplicate_retrieval_benchmark(tmp_path: Path):
    report = tmp_path / "overlap.json"
    result = _run(str(OVERLAP_AUDIT), str(DATASET), "--output", str(report))
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["exact_duplicate_count"] == 0
    assert payload["similarity_warning_count"] == 0


def test_actual_dev_dataset_integrates_with_offline_deterministic_scorer(tmp_path: Path):
    responses = tmp_path / "responses"
    _write_synthetic_responses(responses)
    output = tmp_path / "score"
    result = _run(
        str(SCORER), "--dataset", str(DATASET), "--responses-dir", str(responses),
        "--split", "dev", "--output-dir", str(output),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    aggregate = json.loads((output / "dev_aggregate_metrics.json").read_text(encoding="utf-8"))
    assert aggregate["expected_question_count"] == 20
    assert aggregate["missing_response_count"] == 0
    assert aggregate["answer_status_accuracy"] == 1.0
    assert aggregate["claim_citation_coverage"] == 1.0
    assert aggregate["deterministic_citation_validity"] == 1.0
    assert aggregate["required_source_coverage"] == 1.0
    assert aggregate["abstention_precision"] == 1.0
    assert aggregate["abstention_recall"] == 1.0


def test_semantic_calibration_template_is_blank_and_stratified(tmp_path: Path):
    responses = tmp_path / "responses"
    _write_synthetic_responses(responses)
    output = tmp_path / "calibration.json"
    result = _run(
        str(CALIBRATION), "--dataset", str(DATASET), "--selection", str(SELECTION),
        "--responses-dir", str(responses), "--output", str(output),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert len(payload["questions"]) == 9
    assert payload["labels_prefilled"] is False
    assert any(q["expected_status"] == "insufficient_evidence" for q in payload["questions"])
    for q in payload["questions"]:
        assert q["answer_relevance_score"] is None
        assert all(c["support_label"] is None for c in q["claims"])
        assert all(r["entailment_label"] is None for r in q["citation_relations"])
        assert all(g["coverage_label"] is None for g in q["gold_claims"])
