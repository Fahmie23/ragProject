"""Stage 11 deterministic answer/citation evaluation metrics.

This module deliberately evaluates only properties that can be checked without a
semantic judge. Claim correctness, citation entailment, answer completeness and
answer relevance are defined in the Stage 11 methodology but are not guessed here.

The goal is to keep evaluation diagnostics separate from the frozen production
pipeline. Nothing in this module is imported by retrieval or generation runtime code.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import fmean
from typing import Any, Iterable, Sequence

ANSWER_CITATION_HELDOUT_CONFIRMATION = "RUN_FROZEN_ANSWER_CITATION_HELDOUT_V1"
VALID_STATUSES = {"answered", "insufficient_evidence"}


def enforce_answer_citation_split_policy(*, split: str, confirmation: str | None, benchmark_status: str) -> None:
    """Protect the Stage 11 held-out split from accidental use during development."""

    if split not in {"dev", "heldout"}:
        raise ValueError("split must be 'dev' or 'heldout'")
    if split == "dev":
        return
    if benchmark_status != "frozen":
        raise ValueError("held-out answer/citation evaluation requires benchmark status='frozen'")
    if confirmation != ANSWER_CITATION_HELDOUT_CONFIRMATION:
        raise ValueError(
            "held-out answer/citation evaluation is protected; pass "
            f"--confirm-heldout {ANSWER_CITATION_HELDOUT_CONFIRMATION} only after the Stage 11 rubric and benchmark are frozen"
        )


def _unique_preserve_order(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value)
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _normalize_locator_label(value: str) -> str:
    return " ".join(str(value).split()).casefold()


def _locator_matches(actual: dict[str, Any], gold: dict[str, Any]) -> bool:
    """Strict structural locator match with optional page constraint.

    Gold labels may intentionally omit pages. When pages are supplied, all gold
    pages must be contained within the actual locator pages. This avoids accepting
    a same-named clause from an unrelated page while allowing multi-page chunks.
    """

    if str(actual.get("kind")) != str(gold.get("kind")):
        return False
    if _normalize_locator_label(actual.get("label", "")) != _normalize_locator_label(gold.get("label", "")):
        return False
    gold_pages = {int(page) for page in gold.get("pages", [])}
    actual_pages = {int(page) for page in actual.get("pages", [])}
    return not gold_pages or gold_pages.issubset(actual_pages)


def validate_response_invariants(response: dict[str, Any], *, expected_citation_version: str = "deterministic_citations_v1_2") -> list[str]:
    """Return deterministic Stage 9/10 contract violations for one response."""

    errors: list[str] = []
    status = response.get("status")
    if status not in VALID_STATUSES:
        errors.append(f"invalid status: {status!r}")

    if response.get("citation_version") != expected_citation_version:
        errors.append(
            f"citation_version mismatch: {response.get('citation_version')!r} != {expected_citation_version!r}"
        )

    validation = response.get("citation_validation") or {}
    citations = response.get("citations") or []
    claims = response.get("claims") or []
    evidence_items = response.get("evidence") or []
    evidence = {
        item.get("evidence_id"): item
        for item in evidence_items
        if isinstance(item, dict) and item.get("evidence_id")
    }
    citation_by_id = {
        item.get("citation_id"): item
        for item in citations
        if isinstance(item, dict) and item.get("citation_id")
    }

    if validation.get("status") != "valid":
        errors.append(f"citation_validation.status={validation.get('status')!r}")
    if validation.get("errors"):
        errors.append(f"citation_validation.errors={validation.get('errors')!r}")
    if validation.get("citation_count") != len(citation_by_id):
        errors.append("citation_validation.citation_count does not match unique citations")
    if validation.get("valid_citation_count") != len(citation_by_id):
        errors.append("citation_validation.valid_citation_count does not match unique citations")

    if status == "insufficient_evidence":
        if claims:
            errors.append("abstention returned claims")
        if citations:
            errors.append("abstention returned citations")
        if response.get("used_evidence_ids"):
            errors.append("abstention returned used_evidence_ids")
        if response.get("cited_answer") != response.get("answer"):
            errors.append("abstention cited_answer must equal answer")
        return errors

    if not claims:
        errors.append("answered response has no claims")
    if not citations:
        errors.append("answered response has no citations")

    expected_used: list[str] = []
    cited_answer = str(response.get("cited_answer") or "")
    for claim in claims:
        claim_id = claim.get("claim_id")
        evidence_ids = _unique_preserve_order(claim.get("evidence_ids") or [])
        citation_ids = _unique_preserve_order(claim.get("citation_ids") or [])
        if not evidence_ids:
            errors.append(f"{claim_id} has no evidence_ids")
        if not citation_ids:
            errors.append(f"{claim_id} has no citation_ids")

        mapped_ids: list[str] = []
        for citation_id in citation_ids:
            citation = citation_by_id.get(citation_id)
            if citation is None:
                errors.append(f"{claim_id} references missing citation {citation_id}")
                continue
            mapped_ids.append(str(citation.get("evidence_id")))
        if mapped_ids != evidence_ids:
            errors.append(f"{claim_id} citation/evidence mapping is not deterministic: {mapped_ids} != {evidence_ids}")
        for evidence_id in evidence_ids:
            if evidence_id not in expected_used:
                expected_used.append(evidence_id)

    if expected_used != list(response.get("used_evidence_ids") or []):
        errors.append(f"used_evidence_ids disagree with claims: {expected_used} != {response.get('used_evidence_ids')}")

    for citation_id, citation in citation_by_id.items():
        evidence_id = citation.get("evidence_id")
        ev = evidence.get(evidence_id)
        if ev is None:
            errors.append(f"{citation_id} maps to unknown evidence {evidence_id}")
            continue
        if citation.get("validation_status") != "valid":
            errors.append(f"{citation_id} validation_status is not valid")
        if citation.get("chunk_id") != ev.get("chunk_id") or citation.get("chunk_index") != ev.get("chunk_index"):
            errors.append(f"{citation_id} chunk provenance differs from {evidence_id}")
        if citation.get("pages") != ev.get("pages"):
            errors.append(f"{citation_id} pages differ from {evidence_id}")
        if citation.get("source_element_ids") != ev.get("source_element_ids"):
            errors.append(f"{citation_id} source elements differ from {evidence_id}")
        marker = str(citation.get("marker") or "")
        if not marker or marker not in cited_answer:
            errors.append(f"{citation_id} marker is missing from cited_answer")
        locators = citation.get("locators") or []
        if not locators:
            errors.append(f"{citation_id} has no locators")
        citation_pages = {int(page) for page in citation.get("pages") or []}
        citation_elements = set(citation.get("source_element_ids") or [])
        for locator in locators:
            if not {int(page) for page in locator.get("pages") or []}.issubset(citation_pages):
                errors.append(f"{citation_id} locator escapes citation pages")
            if not set(locator.get("source_element_ids") or []).issubset(citation_elements):
                errors.append(f"{citation_id} locator escapes citation source elements")
    return errors


def score_required_source_groups(*, response: dict[str, Any], required_source_groups: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Measure whether each gold source group is represented by a validated locator.

    A group is satisfied when any emitted citation locator matches any locator in
    that group's ``any_of`` list. This is source coverage only; it does not assert
    that the cited source semantically entails a claim.
    """

    groups = list(required_source_groups or [])
    actual_locators: list[dict[str, Any]] = []
    for citation in response.get("citations") or []:
        if citation.get("validation_status") == "valid":
            actual_locators.extend(locator for locator in citation.get("locators") or [] if isinstance(locator, dict))

    satisfied: list[str] = []
    missing: list[str] = []
    for index, group in enumerate(groups, start=1):
        group_id = str(group.get("group_id") or f"G{index}")
        candidates = group.get("any_of") or []
        matched = any(_locator_matches(actual, gold) for actual in actual_locators for gold in candidates)
        (satisfied if matched else missing).append(group_id)

    coverage = (len(satisfied) / len(groups)) if groups else None
    return {
        "required_source_group_count": len(groups),
        "satisfied_source_group_count": len(satisfied),
        "required_source_coverage": coverage,
        "satisfied_source_groups": satisfied,
        "missing_source_groups": missing,
    }


def score_deterministic_response(
    *,
    response: dict[str, Any],
    expected_status: str,
    required_source_groups: Sequence[dict[str, Any]] | None = None,
    expected_citation_version: str = "deterministic_citations_v1_2",
) -> dict[str, Any]:
    """Score one Stage 11 record using deterministic-only metrics."""

    if expected_status not in VALID_STATUSES:
        raise ValueError(f"expected_status must be one of {sorted(VALID_STATUSES)}")

    actual_status = response.get("status")
    claims = response.get("claims") or []
    covered_claims = sum(1 for claim in claims if claim.get("citation_ids"))
    claim_citation_coverage = (covered_claims / len(claims)) if claims else (1.0 if actual_status == "insufficient_evidence" else 0.0)
    invariant_errors = validate_response_invariants(
        response,
        expected_citation_version=expected_citation_version,
    )
    source_metrics = score_required_source_groups(
        response=response,
        required_source_groups=list(required_source_groups or []),
    )

    result = {
        "expected_status": expected_status,
        "actual_status": actual_status,
        "answer_status_accuracy": 1.0 if actual_status == expected_status else 0.0,
        "expected_abstention": expected_status == "insufficient_evidence",
        "actual_abstention": actual_status == "insufficient_evidence",
        "claim_count": len(claims),
        "claims_with_citations": covered_claims,
        "claim_citation_coverage": claim_citation_coverage,
        "deterministic_citation_validity": 1.0 if not invariant_errors else 0.0,
        "invariant_errors": invariant_errors,
    }
    result.update(source_metrics)
    return result


def aggregate_deterministic_results(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Macro aggregate deterministic Stage 11 rows, including abstention metrics."""

    metrics_rows = [row.get("metrics", row) for row in rows]
    if not metrics_rows:
        return {
            "question_count": 0,
            "valid": False,
            "answer_status_accuracy": None,
            "claim_citation_coverage": None,
            "deterministic_citation_validity": None,
            "abstention_precision": None,
            "abstention_recall": None,
            "abstention_f1": None,
        }

    def avg(key: str) -> float:
        return fmean(float(row[key]) for row in metrics_rows)

    tp = sum(1 for row in metrics_rows if row.get("expected_abstention") and row.get("actual_abstention"))
    fp = sum(1 for row in metrics_rows if not row.get("expected_abstention") and row.get("actual_abstention"))
    fn = sum(1 for row in metrics_rows if row.get("expected_abstention") and not row.get("actual_abstention"))
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * precision * recall / (precision + recall)) if precision is not None and recall is not None and (precision + recall) else None

    source_coverage_values = [
        float(row["required_source_coverage"])
        for row in metrics_rows
        if row.get("required_source_coverage") is not None
    ]
    invariant_error_count = sum(len(row.get("invariant_errors") or []) for row in metrics_rows)

    return {
        "question_count": len(metrics_rows),
        "valid": invariant_error_count == 0,
        "answer_status_accuracy": avg("answer_status_accuracy"),
        "claim_citation_coverage": avg("claim_citation_coverage"),
        "deterministic_citation_validity": avg("deterministic_citation_validity"),
        "required_source_coverage": fmean(source_coverage_values) if source_coverage_values else None,
        "abstention_true_positive": tp,
        "abstention_false_positive": fp,
        "abstention_false_negative": fn,
        "abstention_precision": precision,
        "abstention_recall": recall,
        "abstention_f1": f1,
        "invariant_error_count": invariant_error_count,
    }


def grouped_deterministic_aggregates(rows: Sequence[dict[str, Any]], *, field: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get(field) is not None:
            groups[str(row[field])].append(row)
    return {name: aggregate_deterministic_results(items) for name, items in sorted(groups.items())}
