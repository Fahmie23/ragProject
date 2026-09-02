#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from collections import Counter

ALLOWED_SPLITS = {"dev", "heldout"}
ALLOWED_DIFFICULTIES = {"easy", "medium", "hard"}
ALLOWED_CATEGORIES = {
    "definition", "direct_requirement", "paraphrase", "multi_clause",
    "table_form", "appendix", "cross_page", "exception_condition",
    "cross_reference",
}

def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, type=Path)
    ap.add_argument("--stage5", required=True, type=Path)
    ap.add_argument("--pdf", type=Path)
    args = ap.parse_args()

    dataset = load_json(args.dataset)
    stage5 = load_json(args.stage5)
    errors: list[str] = []

    if dataset.get("document", {}).get("document_id") != stage5.get("document_id"):
        errors.append("document_id mismatch")

    if dataset.get("document", {}).get("source_sha256") != stage5.get("source_sha256"):
        errors.append("source_sha256 mismatch between dataset and Stage 5")

    if dataset.get("chunk_corpus", {}).get("stage5_strategy_version") != stage5.get("strategy_version"):
        errors.append("Stage 5 strategy_version mismatch")

    if args.pdf:
        actual_sha = hashlib.sha256(args.pdf.read_bytes()).hexdigest()
        if actual_sha != dataset.get("document", {}).get("source_sha256"):
            errors.append("PDF SHA-256 mismatch")

    chunks = stage5.get("chunks", [])
    chunk_ids = {c["chunk_id"] for c in chunks}
    chunk_indices = {c["chunk_index"] for c in chunks}

    questions = dataset.get("questions", [])
    if not 30 <= len(questions) <= 40:
        errors.append(f"expected 30-40 formal questions, got {len(questions)}")

    ids = [q.get("question_id") for q in questions]
    if len(ids) != len(set(ids)):
        errors.append("duplicate question_id")

    for q in questions:
        qid = q.get("question_id", "<missing>")
        if q.get("split") not in ALLOWED_SPLITS:
            errors.append(f"{qid}: invalid split")
        if q.get("difficulty") not in ALLOWED_DIFFICULTIES:
            errors.append(f"{qid}: invalid difficulty")
        if q.get("category") not in ALLOWED_CATEGORIES:
            errors.append(f"{qid}: invalid category")
        if q.get("answerable") is not True:
            errors.append(f"{qid}: v1 formal retrieval questions must be answerable")

        gold = q.get("gold", {})
        primary = gold.get("primary_chunk_ids", [])
        supporting = gold.get("supporting_chunk_ids", [])
        primary_idx = gold.get("primary_chunk_indices", [])
        supporting_idx = gold.get("supporting_chunk_indices", [])
        groups = gold.get("required_evidence_groups", [])

        if not primary:
            errors.append(f"{qid}: no primary_chunk_ids")

        for x in primary + supporting:
            if x not in chunk_ids:
                errors.append(f"{qid}: unknown chunk_id {x}")

        for x in primary_idx + supporting_idx:
            if x not in chunk_indices:
                errors.append(f"{qid}: unknown chunk_index {x}")

        if set(primary) & set(supporting):
            errors.append(f"{qid}: primary/supporting overlap")

        group_union = {x for group in groups for x in group}
        if not set(primary).issubset(group_union):
            errors.append(f"{qid}: every primary chunk must appear in required_evidence_groups")

    split_counts = Counter(q["split"] for q in questions)
    if split_counts != Counter({"dev": 25, "heldout": 15}):
        errors.append(f"unexpected split counts: {dict(split_counts)}")

    expected_categories = {
        "definition": 5,
        "direct_requirement": 6,
        "paraphrase": 6,
        "multi_clause": 5,
        "table_form": 4,
        "appendix": 4,
        "cross_page": 3,
        "exception_condition": 4,
        "cross_reference": 3,
    }
    category_counts = Counter(q["category"] for q in questions)
    if dict(category_counts) != expected_categories:
        errors.append(f"unexpected category counts: {dict(category_counts)}")

    print(f"Dataset: {args.dataset}")
    print(f"Stage 5: {args.stage5}")
    print(f"Questions: {len(questions)}")
    print(f"Splits: {dict(split_counts)}")
    print(f"Categories: {dict(category_counts)}")
    print(f"Stage 5 chunks: {len(chunks)}")

    if errors:
        print("\nFAIL")
        for err in errors:
            print(f"- {err}")
        return 1

    print("\nPASS: retrieval evaluation dataset is internally consistent with the Stage 5 corpus.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
