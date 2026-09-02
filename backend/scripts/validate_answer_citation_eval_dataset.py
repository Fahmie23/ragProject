#!/usr/bin/env python3
"""Validate the Stage 11 answer/citation benchmark without external JSON-schema dependencies."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

QUESTION_ID_RE = re.compile(r"^ACIT-[0-9]{3}$")
GROUP_ID_RE = re.compile(r"^G[0-9]+$")
CLAIM_ID_RE = re.compile(r"^GC[0-9]+$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
VALID_SPLITS = {"dev", "heldout"}
VALID_STATUSES = {"answered", "insufficient_evidence"}
VALID_CATEGORIES = {
    "definition", "direct_requirement", "multi_clause", "exception_condition",
    "table_form", "appendix", "cross_page", "cross_reference", "out_of_scope",
}
VALID_DIFFICULTIES = {"easy", "medium", "hard"}
VALID_LOCATOR_KINDS = {"clause", "subclause", "definition", "appendix", "section", "page"}


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("dataset root must be a JSON object")
    return value


def validate_dataset(data: dict) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != "1.0":
        errors.append("schema_version must be '1.0'")
    if data.get("benchmark_status") not in {"draft", "frozen"}:
        errors.append("benchmark_status must be 'draft' or 'frozen'")

    document = data.get("document") or {}
    if not str(document.get("document_id") or "").strip():
        errors.append("document.document_id is required")
    if not SHA_RE.fullmatch(str(document.get("source_sha256") or "")):
        errors.append("document.source_sha256 must be a lowercase SHA-256")
    if not isinstance(document.get("pdf_page_count"), int) or document.get("pdf_page_count", 0) < 1:
        errors.append("document.pdf_page_count must be >= 1")

    policy = data.get("policy") or {}
    expected_policy = {
        "retrieval_profile": "retrieval_v1_stage8_2_top5",
        "retrieval_v1_frozen": True,
        "stage4_frozen": True,
        "stage5_frozen": True,
        "stage10_frozen": True,
        "citation_version": "deterministic_citations_v1_2",
        "heldout_tuning_forbidden": True,
    }
    for key, expected in expected_policy.items():
        if policy.get(key) != expected:
            errors.append(f"policy.{key} must be {expected!r}")

    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        errors.append("questions must be a non-empty array")
        return errors

    seen_question_ids: set[str] = set()
    actual_counts = Counter()
    for index, question in enumerate(questions, start=1):
        prefix = f"questions[{index - 1}]"
        if not isinstance(question, dict):
            errors.append(f"{prefix} must be an object")
            continue
        question_id = str(question.get("question_id") or "")
        if not QUESTION_ID_RE.fullmatch(question_id):
            errors.append(f"{prefix}.question_id must match ACIT-###")
        elif question_id in seen_question_ids:
            errors.append(f"duplicate question_id: {question_id}")
        seen_question_ids.add(question_id)

        split = question.get("split")
        status = question.get("expected_status")
        category = question.get("category")
        difficulty = question.get("difficulty")
        if split not in VALID_SPLITS:
            errors.append(f"{question_id}.split is invalid")
        else:
            actual_counts[split] += 1
        if status not in VALID_STATUSES:
            errors.append(f"{question_id}.expected_status is invalid")
        else:
            actual_counts[status] += 1
        if category not in VALID_CATEGORIES:
            errors.append(f"{question_id}.category is invalid")
        if difficulty not in VALID_DIFFICULTIES:
            errors.append(f"{question_id}.difficulty is invalid")
        if len(str(question.get("question") or "").strip()) < 10:
            errors.append(f"{question_id}.question must be at least 10 characters")

        gold = question.get("gold")
        if not isinstance(gold, dict):
            errors.append(f"{question_id}.gold must be an object")
            continue
        required_claims = gold.get("required_claims")
        source_groups = gold.get("required_source_groups")
        if not isinstance(required_claims, list):
            errors.append(f"{question_id}.gold.required_claims must be an array")
            required_claims = []
        if not isinstance(source_groups, list):
            errors.append(f"{question_id}.gold.required_source_groups must be an array")
            source_groups = []
        if not isinstance(gold.get("answer_notes"), str):
            errors.append(f"{question_id}.gold.answer_notes must be a string")

        if status == "answered" and not required_claims:
            errors.append(f"{question_id} is answerable but has no required_claims")
        if status == "answered" and not source_groups:
            errors.append(f"{question_id} is answerable but has no required_source_groups")
        if status == "insufficient_evidence" and required_claims:
            errors.append(f"{question_id} should abstain but has required_claims")
        if status == "insufficient_evidence" and source_groups:
            errors.append(f"{question_id} should abstain but has required_source_groups")
        if category == "out_of_scope" and status != "insufficient_evidence":
            errors.append(f"{question_id} out_of_scope questions must expect insufficient_evidence")

        claim_ids: set[str] = set()
        for claim in required_claims:
            claim_id = str(claim.get("claim_id") or "") if isinstance(claim, dict) else ""
            if not CLAIM_ID_RE.fullmatch(claim_id):
                errors.append(f"{question_id} gold claim_id must match GC#")
            elif claim_id in claim_ids:
                errors.append(f"{question_id} duplicate gold claim_id: {claim_id}")
            claim_ids.add(claim_id)
            if not isinstance(claim, dict) or not str(claim.get("requirement") or "").strip():
                errors.append(f"{question_id}.{claim_id or 'gold_claim'} requirement is required")

        group_ids: set[str] = set()
        for group in source_groups:
            if not isinstance(group, dict):
                errors.append(f"{question_id} source group must be an object")
                continue
            group_id = str(group.get("group_id") or "")
            if not GROUP_ID_RE.fullmatch(group_id):
                errors.append(f"{question_id} source group_id must match G#")
            elif group_id in group_ids:
                errors.append(f"{question_id} duplicate source group_id: {group_id}")
            group_ids.add(group_id)
            any_of = group.get("any_of")
            if not isinstance(any_of, list) or not any_of:
                errors.append(f"{question_id}.{group_id or 'source_group'}.any_of must be non-empty")
                continue
            for locator in any_of:
                if not isinstance(locator, dict):
                    errors.append(f"{question_id}.{group_id} locator must be an object")
                    continue
                if locator.get("kind") not in VALID_LOCATOR_KINDS:
                    errors.append(f"{question_id}.{group_id} locator kind is invalid")
                if not str(locator.get("label") or "").strip():
                    errors.append(f"{question_id}.{group_id} locator label is required")
                pages = locator.get("pages", [])
                if not isinstance(pages, list) or any(not isinstance(page, int) or page < 1 for page in pages):
                    errors.append(f"{question_id}.{group_id} locator pages must be positive integers")
                elif len(pages) != len(set(pages)):
                    errors.append(f"{question_id}.{group_id} locator pages must be unique")
                elif any(page > int(document.get("pdf_page_count", 0) or 0) for page in pages):
                    errors.append(f"{question_id}.{group_id} locator page exceeds document page count")

    counts = data.get("counts") or {}
    expected_counts = {
        "questions": len(questions),
        "dev": actual_counts["dev"],
        "heldout": actual_counts["heldout"],
        "answered": actual_counts["answered"],
        "insufficient_evidence": actual_counts["insufficient_evidence"],
    }
    for key, expected in expected_counts.items():
        if counts.get(key) != expected:
            errors.append(f"counts.{key}={counts.get(key)!r}, expected {expected}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a Stage 11 answer/citation evaluation dataset")
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    data = _load(args.dataset)
    errors = validate_dataset(data)
    if errors:
        print(f"FAIL: {len(errors)} validation error(s)")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"PASS: {args.dataset}")
    print(f"Questions: {len(data['questions'])}")
    print(f"Benchmark status: {data['benchmark_status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
