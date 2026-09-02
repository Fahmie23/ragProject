#!/usr/bin/env python3
"""Audit Stage 11 DEV questions for accidental reuse of retrieval-evaluation questions."""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RETRIEVAL = BACKEND_ROOT / "evaluation" / "retrieval" / "retrieval_eval_v1.csv"
TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)


def _norm(text: str) -> str:
    return " ".join(TOKEN_RE.findall(str(text).casefold()))


def _tokens(text: str) -> set[str]:
    return set(TOKEN_RE.findall(str(text).casefold()))


def _jaccard(a: str, b: str) -> float:
    aa, bb = _tokens(a), _tokens(b)
    return len(aa & bb) / len(aa | bb) if aa or bb else 1.0


def _load_dataset(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("dataset root must be an object")
    return value


def _load_retrieval(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit Stage 11 DEV/retrieval benchmark question overlap")
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--retrieval-dataset", type=Path, default=DEFAULT_RETRIEVAL)
    ap.add_argument("--warn-jaccard", type=float, default=0.70)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()

    dataset = _load_dataset(args.dataset)
    retrieval = _load_retrieval(args.retrieval_dataset)
    retrieval_questions = [str(row.get("question") or "") for row in retrieval]
    exact = {_norm(text) for text in retrieval_questions}
    rows = []
    duplicate_count = 0
    warning_count = 0
    for q in dataset.get("questions") or []:
        text = str(q.get("question") or "")
        normalized = _norm(text)
        is_duplicate = normalized in exact
        if is_duplicate:
            duplicate_count += 1
        best_text = ""
        best_score = -1.0
        for candidate in retrieval_questions:
            score = _jaccard(text, candidate)
            if score > best_score:
                best_score = score
                best_text = candidate
        warning = (not is_duplicate) and best_score >= args.warn_jaccard
        warning_count += int(warning)
        rows.append({
            "question_id": q.get("question_id"),
            "question": text,
            "exact_duplicate": is_duplicate,
            "max_token_jaccard": round(best_score, 4),
            "nearest_retrieval_question": best_text,
            "similarity_warning": warning,
        })

    report = {
        "dataset_id": dataset.get("dataset_id"),
        "retrieval_dataset": str(args.retrieval_dataset),
        "question_count": len(rows),
        "exact_duplicate_count": duplicate_count,
        "similarity_warning_threshold": args.warn_jaccard,
        "similarity_warning_count": warning_count,
        "rows": rows,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Questions audited: {len(rows)}")
    print(f"Exact retrieval-question duplicates: {duplicate_count}")
    print(f"Similarity warnings >= {args.warn_jaccard:.2f}: {warning_count}")
    for row in rows:
        if row["exact_duplicate"] or row["similarity_warning"]:
            print(f"- {row['question_id']} jaccard={row['max_token_jaccard']}: {row['nearest_retrieval_question']}")
    return 1 if duplicate_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
