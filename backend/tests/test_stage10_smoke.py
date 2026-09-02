from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "test_cited_generation_behaviors.py"
spec = importlib.util.spec_from_file_location("stage10_smoke_script", SCRIPT_PATH)
assert spec and spec.loader
stage10_smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage10_smoke)


def _answered_payload():
    return {
        "status": "answered",
        "answer": "Supported answer.",
        "cited_answer": "Supported answer. [1]",
        "claims": [{"claim_id": "C1", "text": "Supported answer.", "evidence_ids": ["E1"], "citation_ids": ["CIT-E1"]}],
        "used_evidence_ids": ["E1"],
        "citation_version": "deterministic_citations_v1_2",
        "citation_validation": {"status": "valid", "citation_count": 1, "valid_citation_count": 1, "errors": []},
        "evidence": [{
            "evidence_id": "E1", "chunk_id": "c1", "chunk_index": 1, "pages": [38],
            "source_element_ids": ["p38-e1"],
        }],
        "citations": [{
            "citation_id": "CIT-E1", "marker": "[1]", "evidence_id": "E1", "chunk_id": "c1", "chunk_index": 1,
            "source_filename": "source.pdf", "display": "Clause 8.1.25 · PDF p. 38", "pages": [38],
            "source_element_ids": ["p38-e1"], "validation_status": "valid",
            "locators": [{"kind": "clause", "label": "Clause 8.1.25", "pages": [38], "source_element_ids": ["p38-e1"]}],
        }],
    }


def test_stage10_smoke_accepts_valid_answered_payload():
    assert stage10_smoke._validate_stage10_payload(_answered_payload(), "answerable") == []


def test_stage10_smoke_rejects_invented_citation_source_element():
    payload = _answered_payload()
    payload["citations"][0]["source_element_ids"] = ["invented"]
    errors = stage10_smoke._validate_stage10_payload(payload, "answerable")
    assert any("source elements differ" in error for error in errors)


def test_stage10_smoke_accepts_clean_abstention():
    payload = {
        "status": "insufficient_evidence",
        "answer": "The retrieved evidence is insufficient to answer this question reliably.",
        "cited_answer": "The retrieved evidence is insufficient to answer this question reliably.",
        "claims": [],
        "used_evidence_ids": [],
        "evidence": [],
        "citations": [],
        "citation_version": "deterministic_citations_v1_2",
        "citation_validation": {"status": "valid", "citation_count": 0, "valid_citation_count": 0, "errors": []},
    }
    assert stage10_smoke._validate_stage10_payload(payload, "should_abstain") == []
