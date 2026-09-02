#!/usr/bin/env python3
"""Audit Stage 11 held-out independence from DEV and retrieval benchmarks.

This is a construction-time guard. It compares question wording against both prior
benchmarks and also requires that no exact Stage 11 DEV gold locator is reused by
the held-out benchmark. It never calls retrieval or generation.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEV = BACKEND_ROOT / "evaluation" / "generation" / "answer_citation_eval_dev_v1.json"
DEFAULT_RETRIEVAL = BACKEND_ROOT / "evaluation" / "retrieval" / "retrieval_eval_v1.csv"
TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _load_retrieval(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _norm(text: str) -> str:
    return " ".join(TOKEN_RE.findall(str(text).casefold()))


def _tokens(text: str) -> set[str]:
    return set(TOKEN_RE.findall(str(text).casefold()))


def _jaccard(a: str, b: str) -> float:
    aa, bb = _tokens(a), _tokens(b)
    return len(aa & bb) / len(aa | bb) if aa or bb else 1.0


def _locator_key(locator: dict[str, Any]) -> tuple[str, str, tuple[int, ...]]:
    return (
        str(locator.get("kind") or ""),
        " ".join(str(locator.get("label") or "").split()).casefold(),
        tuple(int(page) for page in locator.get("pages") or []),
    )


def _stage11_locators(dataset: dict[str, Any]) -> dict[tuple[str, str, tuple[int, ...]], list[str]]:
    result: dict[tuple[str, str, tuple[int, ...]], list[str]] = {}
    for question in dataset.get("questions") or []:
        qid = str(question.get("question_id") or "")
        for group in (question.get("gold") or {}).get("required_source_groups") or []:
            for locator in group.get("any_of") or []:
                result.setdefault(_locator_key(locator), []).append(qid)
    return result


def audit_independence(
    heldout: dict[str, Any],
    *,
    dev: dict[str, Any],
    retrieval_rows: list[dict[str, str]],
    warn_jaccard: float = 0.70,
) -> dict[str, Any]:
    dev_questions = [(str(q.get("question_id")), str(q.get("question") or "")) for q in dev.get("questions") or []]
    retrieval_questions = [(str(row.get("question_id") or ""), str(row.get("question") or "")) for row in retrieval_rows]
    prior_questions = [("stage11_dev", qid, text) for qid, text in dev_questions] + [
        ("retrieval_eval", qid, text) for qid, text in retrieval_questions
    ]
    prior_exact = {_norm(text) for _, _, text in prior_questions}
    prior_ids = {qid for _, qid, _ in prior_questions}

    rows: list[dict[str, Any]] = []
    exact_duplicate_count = 0
    similarity_warning_count = 0
    question_id_collision_count = 0
    for question in heldout.get("questions") or []:
        qid = str(question.get("question_id") or "")
        text = str(question.get("question") or "")
        exact_duplicate = _norm(text) in prior_exact
        exact_duplicate_count += int(exact_duplicate)
        id_collision = qid in prior_ids
        question_id_collision_count += int(id_collision)
        best = max(
            (( _jaccard(text, candidate), source, prior_qid, candidate) for source, prior_qid, candidate in prior_questions),
            default=(0.0, "", "", ""),
            key=lambda item: item[0],
        )
        warning = (not exact_duplicate) and best[0] >= warn_jaccard
        similarity_warning_count += int(warning)
        rows.append({
            "question_id": qid,
            "question": text,
            "question_id_collision": id_collision,
            "exact_duplicate": exact_duplicate,
            "max_token_jaccard": round(best[0], 4),
            "nearest_prior_source": best[1],
            "nearest_prior_question_id": best[2],
            "nearest_prior_question": best[3],
            "similarity_warning": warning,
        })

    dev_locators = _stage11_locators(dev)
    heldout_locators = _stage11_locators(heldout)
    locator_overlap = []
    for key, heldout_qids in heldout_locators.items():
        if key in dev_locators:
            locator_overlap.append({
                "kind": key[0],
                "label": key[1],
                "pages": list(key[2]),
                "heldout_question_ids": heldout_qids,
                "dev_question_ids": dev_locators[key],
            })

    valid = not (
        exact_duplicate_count
        or similarity_warning_count
        or question_id_collision_count
        or locator_overlap
    )
    return {
        "dataset_id": heldout.get("dataset_id"),
        "dev_dataset_id": dev.get("dataset_id"),
        "retrieval_question_count": len(retrieval_rows),
        "question_count": len(rows),
        "similarity_warning_threshold": warn_jaccard,
        "exact_duplicate_count": exact_duplicate_count,
        "similarity_warning_count": similarity_warning_count,
        "question_id_collision_count": question_id_collision_count,
        "exact_dev_gold_locator_overlap_count": len(locator_overlap),
        "valid": valid,
        "locator_overlaps": locator_overlap,
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit Stage 11 held-out independence")
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--dev-dataset", type=Path, default=DEFAULT_DEV)
    ap.add_argument("--retrieval-dataset", type=Path, default=DEFAULT_RETRIEVAL)
    ap.add_argument("--warn-jaccard", type=float, default=0.70)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()

    report = audit_independence(
        _load_json(args.dataset),
        dev=_load_json(args.dev_dataset),
        retrieval_rows=_load_retrieval(args.retrieval_dataset),
        warn_jaccard=args.warn_jaccard,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Questions audited: {report['question_count']}")
    print(f"Exact prior-question duplicates: {report['exact_duplicate_count']}")
    print(f"Similarity warnings >= {report['similarity_warning_threshold']:.2f}: {report['similarity_warning_count']}")
    print(f"Question-ID collisions: {report['question_id_collision_count']}")
    print(f"Exact Stage 11 DEV gold-locator overlaps: {report['exact_dev_gold_locator_overlap_count']}")
    print(f"Status: {'PASS' if report['valid'] else 'FAIL'}")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
