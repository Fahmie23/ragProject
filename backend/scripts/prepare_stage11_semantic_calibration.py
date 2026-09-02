#!/usr/bin/env python3
"""Prepare a blank human semantic-calibration artifact from captured DEV responses."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = BACKEND_ROOT / "evaluation" / "generation" / "answer_citation_eval_dev_v1.json"
DEFAULT_SELECTION = BACKEND_ROOT / "evaluation" / "generation" / "answer_citation_eval_dev_calibration_v1.json"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_calibration(*, dataset: dict[str, Any], selection: dict[str, Any], responses_dir: Path) -> dict[str, Any]:
    by_id = {str(q["question_id"]): q for q in dataset.get("questions") or []}
    questions: list[dict[str, Any]] = []
    for qid in selection.get("question_ids") or []:
        if qid not in by_id:
            raise ValueError(f"calibration selection references unknown question {qid}")
        path = responses_dir / f"{qid}.json"
        if not path.exists():
            raise FileNotFoundError(f"missing captured response for calibration question {qid}: {path}")
        response = _load(path)
        q = by_id[qid]
        citations = {c.get("citation_id"): c for c in response.get("citations") or []}
        claims = []
        relations = []
        for item in response.get("claims") or []:
            claim_id = str(item.get("claim_id"))
            claims.append({
                "claim_id": claim_id,
                "text": item.get("text"),
                "evidence_ids": item.get("evidence_ids") or [],
                "citation_ids": item.get("citation_ids") or [],
                "support_label": None,
                "support_notes": "",
            })
            for citation_id in item.get("citation_ids") or []:
                citation = citations.get(citation_id) or {}
                relations.append({
                    "claim_id": claim_id,
                    "citation_id": citation_id,
                    "evidence_id": citation.get("evidence_id"),
                    "citation_display": citation.get("display"),
                    "entailment_label": None,
                    "entailment_notes": "",
                })
        gold_claims = [
            {
                "claim_id": item.get("claim_id"),
                "requirement": item.get("requirement"),
                "coverage_label": None,
                "coverage_notes": "",
            }
            for item in (q.get("gold") or {}).get("required_claims") or []
        ]
        questions.append({
            "question_id": qid,
            "category": q.get("category"),
            "difficulty": q.get("difficulty"),
            "question": q.get("question"),
            "expected_status": q.get("expected_status"),
            "actual_status": response.get("status"),
            "response_canonical_sha256": _canonical_sha256(response),
            "answer": response.get("answer"),
            "cited_answer": response.get("cited_answer"),
            "claims": claims,
            "citation_relations": relations,
            "gold_claims": gold_claims,
            "answer_relevance_score": None,
            "answer_relevance_notes": "",
            "reviewer_notes": "",
        })
    return {
        "schema_version": "1.0",
        "calibration_id": selection.get("calibration_id"),
        "dataset_id": dataset.get("dataset_id"),
        "dataset_canonical_sha256": _canonical_sha256(dataset),
        "rubric_version": "stage11_semantic_rubric_v1",
        "calibration_status": "draft",
        "human_confirmed": False,
        "allowed_labels": {
            "claim_support": ["supported", "partially_supported", "unsupported", "contradicted"],
            "citation_entailment": ["entails", "partial", "does_not_entail"],
            "gold_claim_coverage": ["covered", "partially_covered", "missing"],
            "answer_relevance": [0, 1, 2]
        },
        "labels_prefilled": False,
        "questions": questions,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Prepare blank Stage 11 semantic calibration JSON")
    ap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    ap.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    ap.add_argument("--responses-dir", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    result = build_calibration(dataset=_load(args.dataset), selection=_load(args.selection), responses_dir=args.responses_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"PASS: prepared {len(result['questions'])} calibration questions")
    print(f"Output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
