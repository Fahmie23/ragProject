from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable


CHILD_SEMANTIC_TYPES = {"list_item", "table", "mixed", "subclause"}
INTRO_PHRASES = (
    "following authorities",
    "following information",
    "following categories",
)


@dataclass(frozen=True)
class StructuralContextConfig:
    """Bounded one-hop context assembly settings.

    Context expansion is intentionally separate from ranking. Expanded chunks never
    receive a retrieval rank and never change Hit@K / Recall@K / MRR.
    """

    max_forward_neighbors_per_seed: int = 2
    max_backward_neighbors_per_seed: int = 1
    max_page_gap: int = 1
    max_context_chunks: int = 30
    same_section_required: bool = True
    recursive: bool = False

    def validate(self) -> None:
        if not 0 <= self.max_forward_neighbors_per_seed <= 4:
            raise ValueError("max_forward_neighbors_per_seed must be between 0 and 4")
        if not 0 <= self.max_backward_neighbors_per_seed <= 2:
            raise ValueError("max_backward_neighbors_per_seed must be between 0 and 2")
        if not 0 <= self.max_page_gap <= 3:
            raise ValueError("max_page_gap must be between 0 and 3")
        if not 1 <= self.max_context_chunks <= 100:
            raise ValueError("max_context_chunks must be between 1 and 100")
        if self.recursive:
            raise ValueError("recursive expansion is deliberately unsupported in structural_one_hop_v1")


def required_neighbor_indices(seed_indices: Iterable[int], config: StructuralContextConfig) -> set[int]:
    config.validate()
    result: set[int] = set()
    for raw_index in seed_indices:
        index = int(raw_index)
        for distance in range(1, config.max_backward_neighbors_per_seed + 1):
            if index - distance >= 0:
                result.add(index - distance)
        for distance in range(1, config.max_forward_neighbors_per_seed + 1):
            result.add(index + distance)
    return result


def assemble_structural_context(
    ranked_hits: list[dict[str, Any]],
    chunk_lookup: dict[int, dict[str, Any]],
    *,
    config: StructuralContextConfig | None = None,
) -> list[dict[str, Any]]:
    """Attach structurally dependent local evidence to ranked seed chunks.

    Rules are deterministic and query-agnostic:
    - a direct following table in the same section;
    - a list-item continuation when the seed visibly ends with ``and`` / ``or``;
    - up to two non-clause children after an explicit introducing statement;
    - the immediately preceding introducing clause for a table/list/mixed/subclause seed.

    Only ranked hits are expansion seeds. Added chunks are never recursively expanded.
    ``source_rank`` records the earliest ranked seed that makes a context chunk available,
    allowing ContextRecall@K to be computed without pretending the chunk was ranked.
    """

    cfg = config or StructuralContextConfig()
    cfg.validate()
    if cfg.max_context_chunks < len(ranked_hits):
        raise ValueError("max_context_chunks must be >= number of ranked hits")

    entries: dict[str, dict[str, Any]] = {}

    # Insert every raw ranked hit first. This preserves the ranked set in context even
    # when no structural expansion applies.
    for hit in ranked_hits:
        item = _context_item(hit)
        item.update(
            source_rank=int(hit["rank"]),
            ranked_seed_rank=int(hit["rank"]),
            reasons=["ranked_seed"],
            attached_from_chunk_ids=[],
        )
        entries[str(hit["chunk_id"])] = item

    for hit in ranked_hits:
        if len(entries) >= cfg.max_context_chunks:
            break
        seed_index = int(hit["chunk_index"])
        seed = chunk_lookup.get(seed_index) or _context_item(hit)
        source_rank = int(hit["rank"])

        for neighbor, reason in _eligible_neighbors(seed, seed_index, chunk_lookup, cfg):
            chunk_id = str(neighbor["chunk_id"])
            if chunk_id in entries:
                existing = entries[chunk_id]
                existing["source_rank"] = min(int(existing["source_rank"]), source_rank)
                if reason not in existing["reasons"]:
                    existing["reasons"].append(reason)
                if str(hit["chunk_id"]) != chunk_id and str(hit["chunk_id"]) not in existing["attached_from_chunk_ids"]:
                    existing["attached_from_chunk_ids"].append(str(hit["chunk_id"]))
                continue
            if len(entries) >= cfg.max_context_chunks:
                break
            item = _context_item(neighbor)
            item.update(
                source_rank=source_rank,
                ranked_seed_rank=None,
                reasons=[reason],
                attached_from_chunk_ids=[str(hit["chunk_id"])],
            )
            entries[chunk_id] = item

    ordered = sorted(
        entries.values(),
        key=lambda item: (
            int(item["source_rank"]),
            int(item["chunk_index"]),
            0 if item.get("ranked_seed_rank") is not None else 1,
        ),
    )
    for context_order, item in enumerate(ordered, start=1):
        item["context_order"] = context_order
    return ordered


def _eligible_neighbors(
    seed: dict[str, Any],
    seed_index: int,
    lookup: dict[int, dict[str, Any]],
    config: StructuralContextConfig,
) -> list[tuple[dict[str, Any], str]]:
    selected: list[tuple[dict[str, Any], str]] = []
    selected_ids: set[str] = set()

    # Backward rule: if a ranked child/table is selected, include the immediate
    # structural lead-in that explicitly introduces it.
    if config.max_backward_neighbors_per_seed:
        previous = lookup.get(seed_index - 1)
        if previous and _compatible(seed, previous, config):
            if str(seed.get("semantic_type")) in CHILD_SEMANTIC_TYPES and _looks_like_intro(previous):
                _append(selected, selected_ids, previous, "preceding_intro")

    if config.max_forward_neighbors_per_seed <= 0:
        return selected

    next_one = lookup.get(seed_index + 1)
    if next_one and _compatible(seed, next_one, config):
        # A table directly following a clause/paragraph is a bounded structural
        # attachment. This handles lead-in text followed by its tabular payload.
        if str(next_one.get("semantic_type")) == "table" and str(seed.get("semantic_type")) != "table":
            _append(selected, selected_ids, next_one, "following_table")
        elif _is_list_continuation(seed, next_one):
            _append(selected, selected_ids, next_one, "continuation_list_item")

    # Explicit introducing statements may own a short sequence of child units.
    # Stop immediately on the first new clause/paragraph/section-like unit, and do
    # not recurse from the children.
    if _looks_like_intro(seed):
        for distance in range(1, config.max_forward_neighbors_per_seed + 1):
            candidate = lookup.get(seed_index + distance)
            if not candidate or not _compatible(seed, candidate, config):
                break
            if str(candidate.get("semantic_type")) not in CHILD_SEMANTIC_TYPES:
                break
            _append(selected, selected_ids, candidate, "introduced_child")

    return selected


def _append(
    selected: list[tuple[dict[str, Any], str]],
    seen: set[str],
    chunk: dict[str, Any],
    reason: str,
) -> None:
    chunk_id = str(chunk["chunk_id"])
    if chunk_id not in seen:
        seen.add(chunk_id)
        selected.append((chunk, reason))


def _compatible(a: dict[str, Any], b: dict[str, Any], config: StructuralContextConfig) -> bool:
    if config.same_section_required and list(a.get("section_path", [])) != list(b.get("section_path", [])):
        return False
    return _page_gap(a, b) <= config.max_page_gap


def _page_gap(a: dict[str, Any], b: dict[str, Any]) -> int:
    pages_a = [int(x) for x in a.get("pages", [])]
    pages_b = [int(x) for x in b.get("pages", [])]
    if not pages_a or not pages_b:
        return 0
    return min(abs(x - y) for x in pages_a for y in pages_b)


def _looks_like_intro(chunk: dict[str, Any]) -> bool:
    text = str(chunk.get("content_text") or "").strip()
    lower = text.lower()
    if text.endswith(":"):
        return True
    if any(phrase in lower for phrase in INTRO_PHRASES):
        return True
    if re.search(r"\bentails?\b.*\b(?:two|three|four|five|\d+)\b.*:", lower, flags=re.DOTALL):
        return True
    if re.search(r"\b(?:includes?|comprises?|consists of|sets out)\b.*:", lower, flags=re.DOTALL):
        return True
    return False


def _is_list_continuation(seed: dict[str, Any], candidate: dict[str, Any]) -> bool:
    if str(candidate.get("semantic_type")) != "list_item":
        return False
    text = str(seed.get("content_text") or "").strip().lower()
    return bool(re.search(r"(?:;\s*)?(?:and|or)\s*$", text))


def _context_item(chunk: dict[str, Any]) -> dict[str, Any]:
    return {
        "context_order": 0,
        "chunk_id": str(chunk["chunk_id"]),
        "chunk_index": int(chunk["chunk_index"]),
        "semantic_type": str(chunk["semantic_type"]),
        "text": str(chunk.get("text") or ""),
        "content_text": str(chunk.get("content_text") or ""),
        "token_count": int(chunk.get("token_count") or 0),
        "pages": list(chunk.get("pages", [])),
        "section_path": list(chunk.get("section_path", [])),
        "source_element_ids": list(chunk.get("source_element_ids", [])),
    }
