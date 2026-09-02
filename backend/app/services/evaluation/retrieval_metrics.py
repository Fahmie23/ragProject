from __future__ import annotations

from collections import defaultdict
from statistics import fmean
from typing import Any, Iterable, Sequence

DEFAULT_KS: tuple[int, ...] = (1, 3, 5, 10)
HELDOUT_CONFIRMATION = "I_HAVE_FROZEN_RETRIEVAL"


def _unique_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value)
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def enforce_split_policy(*, split: str, confirmation: str | None, config_status: str) -> None:
    """Protect the held-out split from accidental inspection during tuning."""

    if split not in {"dev", "heldout"}:
        raise ValueError("split must be 'dev' or 'heldout'")
    if split == "dev":
        return
    if config_status != "frozen":
        raise ValueError("held-out evaluation requires a retrieval configuration with status='frozen'")
    if confirmation != HELDOUT_CONFIRMATION:
        raise ValueError(
            "held-out evaluation is protected; pass "
            f"--confirm-heldout {HELDOUT_CONFIRMATION} only after retrieval is frozen"
        )


def score_ranking(
    *,
    retrieved_chunk_ids: Sequence[str],
    primary_chunk_ids: Sequence[str],
    required_evidence_groups: Sequence[Sequence[str]],
    ks: Sequence[int] = DEFAULT_KS,
) -> dict[str, Any]:
    """Score one ranked list against the authoritative primary evidence labels.

    The runner retrieves up to max(ks). Reciprocal rank is therefore reported as
    MRR@max(ks): a missing primary chunk within that evaluation window scores 0.
    """

    clean_ks = tuple(sorted({int(k) for k in ks if int(k) > 0}))
    if not clean_ks:
        raise ValueError("at least one positive K is required")

    retrieved = _unique_preserve_order(retrieved_chunk_ids)
    primary = set(_unique_preserve_order(primary_chunk_ids))
    if not primary:
        raise ValueError("primary_chunk_ids must not be empty")

    groups = [set(_unique_preserve_order(group)) for group in required_evidence_groups]
    if not groups:
        groups = [{chunk_id} for chunk_id in primary]
    if any(not group for group in groups):
        raise ValueError("required_evidence_groups cannot contain an empty group")

    first_relevant_rank: int | None = None
    for rank, chunk_id in enumerate(retrieved, start=1):
        if chunk_id in primary:
            first_relevant_rank = rank
            break

    result: dict[str, Any] = {
        "retrieved_count": len(retrieved),
        "primary_gold_count": len(primary),
        "first_relevant_rank": first_relevant_rank,
        "reciprocal_rank": (1.0 / first_relevant_rank) if first_relevant_rank else 0.0,
        "mrr_cutoff": max(clean_ks),
    }

    for k in clean_ks:
        top = set(retrieved[:k])
        primary_hits = primary & top
        result[f"hit_at_{k}"] = 1.0 if primary_hits else 0.0
        result[f"recall_at_{k}"] = len(primary_hits) / len(primary)
        result[f"complete_evidence_at_{k}"] = 1.0 if all(group & top for group in groups) else 0.0
        result[f"primary_hits_at_{k}"] = sorted(primary_hits)

    return result




def score_context_assembly(
    *,
    context_chunks: Sequence[dict[str, Any]],
    primary_chunk_ids: Sequence[str],
    required_evidence_groups: Sequence[Sequence[str]],
    ks: Sequence[int] = DEFAULT_KS,
) -> dict[str, Any]:
    """Score context coverage without converting expanded chunks into retrieval ranks.

    A context chunk is available at K when ``source_rank <= K``. The method reports
    separate ContextRecall/ContextCompleteEvidence metrics so raw ranking metrics
    remain scientifically unchanged.
    """

    clean_ks = tuple(sorted({int(k) for k in ks if int(k) > 0}))
    if not clean_ks:
        raise ValueError("at least one positive K is required")
    primary = set(_unique_preserve_order(primary_chunk_ids))
    if not primary:
        raise ValueError("primary_chunk_ids must not be empty")
    groups = [set(_unique_preserve_order(group)) for group in required_evidence_groups]
    if not groups:
        groups = [{chunk_id} for chunk_id in primary]

    result: dict[str, Any] = {}
    for k in clean_ks:
        available = {
            str(item["chunk_id"])
            for item in context_chunks
            if int(item.get("source_rank", 10**9)) <= k
        }
        hits = primary & available
        result[f"context_recall_at_{k}"] = len(hits) / len(primary)
        result[f"context_complete_evidence_at_{k}"] = 1.0 if all(group & available for group in groups) else 0.0
        result[f"context_chunk_count_at_{k}"] = len(available)
        result[f"context_primary_hits_at_{k}"] = sorted(hits)
    return result


def aggregate_scored_results(
    rows: Sequence[dict[str, Any]],
    *,
    ks: Sequence[int] = DEFAULT_KS,
) -> dict[str, Any]:
    """Macro-average successful per-question metric rows."""

    clean_ks = tuple(sorted({int(k) for k in ks if int(k) > 0}))
    successful = [row for row in rows if row.get("status") == "ok" and isinstance(row.get("metrics"), dict)]
    failed = [row for row in rows if row.get("status") != "ok"]

    aggregate: dict[str, Any] = {
        "question_count": len(rows),
        "successful_question_count": len(successful),
        "failed_question_count": len(failed),
        "valid": bool(rows) and not failed,
        "mrr_cutoff": max(clean_ks),
    }
    if not successful:
        aggregate["reciprocal_rank"] = None
        for k in clean_ks:
            aggregate[f"hit_at_{k}"] = None
            aggregate[f"recall_at_{k}"] = None
            aggregate[f"complete_evidence_at_{k}"] = None
        return aggregate

    aggregate["reciprocal_rank"] = fmean(float(row["metrics"]["reciprocal_rank"]) for row in successful)
    for k in clean_ks:
        for prefix in ("hit_at", "recall_at", "complete_evidence_at"):
            key = f"{prefix}_{k}"
            aggregate[key] = fmean(float(row["metrics"][key]) for row in successful)

    context_rows = [row for row in successful if f"context_recall_at_{clean_ks[0]}" in row["metrics"]]
    aggregate["context_question_count"] = len(context_rows)
    if context_rows:
        for k in clean_ks:
            aggregate[f"context_recall_at_{k}"] = fmean(
                float(row["metrics"][f"context_recall_at_{k}"]) for row in context_rows
            )
            aggregate[f"context_complete_evidence_at_{k}"] = fmean(
                float(row["metrics"][f"context_complete_evidence_at_{k}"]) for row in context_rows
            )
            aggregate[f"average_context_chunk_count_at_{k}"] = fmean(
                float(row["metrics"][f"context_chunk_count_at_{k}"]) for row in context_rows
            )
    return aggregate


def grouped_aggregates(
    rows: Sequence[dict[str, Any]],
    *,
    field: str,
    ks: Sequence[int] = DEFAULT_KS,
) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = row.get(field)
        if value is not None:
            groups[str(value)].append(row)
    return {name: aggregate_scored_results(items, ks=ks) for name, items in sorted(groups.items())}
