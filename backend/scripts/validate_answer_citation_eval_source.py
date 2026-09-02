#!/usr/bin/env python3
"""Validate Stage 11 gold source locators against the frozen Stage 4 canonical artifact.

This is a dataset-construction guard only. It does not retrieve, generate, rerank,
or mutate the production pipeline.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANONICAL = BACKEND_ROOT / "evaluation" / "reports" / "sc_aml_cft_diagnostic_replay_stage4.json"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _norm(value: str) -> str:
    return " ".join(str(value).split()).casefold()


def _marker(value: str) -> str:
    value = str(value).strip()
    if not value:
        return ""
    if value.startswith("(") and value.endswith(")"):
        return value
    return f"({value.strip('()')})"


def _clause_path(record: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> str:
    if record.get("kind") == "clause":
        return str(record.get("number") or "").strip()
    suffix: list[str] = []
    current: dict[str, Any] | None = record
    seen: set[str] = set()
    while current is not None and str(current.get("clause_id")) not in seen:
        seen.add(str(current.get("clause_id")))
        if current.get("kind") == "clause":
            return str(current.get("number") or "").strip() + "".join(reversed(suffix))
        suffix.append(_marker(str(current.get("number") or "")))
        current = by_id.get(str(current.get("parent_clause_id") or ""))
    return "".join(reversed(suffix))


def _catalog(canonical: dict[str, Any]) -> list[dict[str, Any]]:
    pages = canonical.get("pages") or []
    element_page: dict[str, int] = {}
    section_content_pages: dict[str, set[int]] = {}
    for page in pages:
        page_number = int(page.get("page_number"))
        for element in page.get("elements") or []:
            eid = str(element.get("element_id") or "")
            if eid:
                element_page[eid] = page_number
            sid = str(element.get("section_id") or "")
            if sid:
                section_content_pages.setdefault(sid, set()).add(page_number)

    rows: list[dict[str, Any]] = []
    clause_by_id = {str(row.get("clause_id")): row for row in canonical.get("clauses") or []}
    for row in canonical.get("clauses") or []:
        path = _clause_path(row, clause_by_id)
        label = f"Clause {path}" if path else f"Subclause {_marker(str(row.get('number') or ''))}"
        rows.append({
            "kind": str(row.get("kind") or "clause"),
            "label": label,
            "pages": {int(row.get("page_number"))},
        })

    for row in canonical.get("definitions") or []:
        rows.append({
            "kind": "definition",
            "label": f"Definition “{row.get('term')}”",
            "pages": set(range(int(row.get("start_page")), int(row.get("end_page")) + 1)),
        })

    for row in canonical.get("appendices") or []:
        rows.append({
            "kind": "appendix",
            "label": str(row.get("label") or ""),
            "pages": set(range(int(row.get("start_page")), int(row.get("end_page")) + 1)),
        })

    for row in canonical.get("sections") or []:
        sid = str(row.get("section_id") or "")
        sec_pages = set(section_content_pages.get(sid, set()))
        sec_pages.add(int(row.get("page_number")))
        rows.append({
            "kind": "section",
            "label": str(row.get("title") or ""),
            "pages": sec_pages,
        })

    for page in pages:
        page_number = int(page.get("page_number"))
        rows.append({"kind": "page", "label": f"PDF p. {page_number}", "pages": {page_number}})
    return rows


def validate_source(dataset: dict[str, Any], canonical: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    doc = dataset.get("document") or {}
    expected_page_count = len(canonical.get("pages") or [])
    checks = {
        "document_id": canonical.get("document_id"),
        "source_sha256": canonical.get("source_sha256"),
        "pdf_page_count": expected_page_count,
    }
    for key, expected in checks.items():
        if doc.get(key) != expected:
            errors.append(f"document.{key}={doc.get(key)!r}, canonical={expected!r}")

    catalog = _catalog(canonical)
    for question in dataset.get("questions") or []:
        qid = question.get("question_id")
        for group in (question.get("gold") or {}).get("required_source_groups") or []:
            gid = group.get("group_id")
            for locator in group.get("any_of") or []:
                kind = str(locator.get("kind") or "")
                label = str(locator.get("label") or "")
                gold_pages = {int(p) for p in locator.get("pages") or []}
                matches = [
                    row for row in catalog
                    if row["kind"] == kind and _norm(row["label"]) == _norm(label)
                ]
                if not matches:
                    errors.append(f"{qid}.{gid}: unknown canonical locator {kind}:{label!r}")
                    continue
                if gold_pages and not any(gold_pages.issubset(row["pages"]) for row in matches):
                    available = sorted({page for row in matches for page in row["pages"]})
                    errors.append(
                        f"{qid}.{gid}: locator {kind}:{label!r} pages {sorted(gold_pages)} "
                        f"not supported by canonical pages {available}"
                    )
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate Stage 11 gold source locators against canonical Stage 4")
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    args = ap.parse_args()
    dataset = _load(args.dataset)
    canonical = _load(args.canonical)
    errors = validate_source(dataset, canonical)
    if errors:
        print(f"FAIL: {len(errors)} source-validation error(s)")
        for error in errors:
            print(f"- {error}")
        return 1
    group_count = sum(len((q.get("gold") or {}).get("required_source_groups") or []) for q in dataset.get("questions") or [])
    locator_count = sum(
        len(group.get("any_of") or [])
        for q in dataset.get("questions") or []
        for group in (q.get("gold") or {}).get("required_source_groups") or []
    )
    print(f"PASS: {args.dataset}")
    print(f"Canonical source: {args.canonical}")
    print(f"Questions: {len(dataset.get('questions') or [])}")
    print(f"Required source groups: {group_count}")
    print(f"Gold locators checked: {locator_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
