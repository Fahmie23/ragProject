from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import re

from app.schemas import (
    ChunkAgentCandidate,
    ChunkingArtifact,
    ChunkQualityIssue,
    ChunkQualityReport,
    ChunkQualitySummary,
    ResolvedStructureArtifact,
    RetrievalChunk,
)


_CONTEXTUAL_NOTE_RE = re.compile(r"^\s*\d{1,3}\s+[A-Z][^\n]{4,}")
_LOW_INFORMATION_TYPES = {"figure", "paragraph", "document_metadata", "caption"}


def _stable_id(prefix: str, values: list[str]) -> str:
    digest = sha256("\n".join(values).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _is_navigation_chunk(chunk: RetrievalChunk) -> bool:
    if not chunk.section_path:
        return False
    first = " ".join(chunk.section_path[0].split()).strip().lower().rstrip(":")
    return first in {"contents", "table of contents"} or first.startswith("contents ")


def _chunk_preview(chunks: list[RetrievalChunk], limit: int = 420) -> str:
    text = "\n\n".join(chunk.content_text.strip() for chunk in chunks if chunk.content_text.strip())
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else f"{compact[: limit - 1].rstrip()}…"


def _merge_candidate_groups(groups: list[tuple[set[str], set[str]]]) -> list[tuple[set[str], set[str]]]:
    """Merge overlapping candidate groups so Stage 5.1 plans never fight each other."""

    merged: list[tuple[set[str], set[str]]] = []
    for ids, reasons in groups:
        if not ids:
            continue
        current_ids = set(ids)
        current_reasons = set(reasons)
        changed = True
        while changed:
            changed = False
            remaining: list[tuple[set[str], set[str]]] = []
            for existing_ids, existing_reasons in merged:
                if current_ids & existing_ids:
                    current_ids |= existing_ids
                    current_reasons |= existing_reasons
                    changed = True
                else:
                    remaining.append((existing_ids, existing_reasons))
            merged = remaining
        merged.append((current_ids, current_reasons))
    return merged


def analyze_chunk_quality(
    *,
    baseline: ChunkingArtifact,
    resolved: ResolvedStructureArtifact,
    tiny_chunk_threshold: int = 60,
) -> ChunkQualityReport:
    """Analyze the deterministic Stage 5 artifact without changing it.

    The quality gate intentionally avoids a made-up scalar "quality score". It
    reports concrete retrieval risks and builds bounded, non-overlapping
    candidates for the optional Stage 5.1 planner.
    """

    chunks = sorted(baseline.chunks, key=lambda item: item.chunk_index)
    chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    index_by_id = {chunk.chunk_id: chunk.chunk_index for chunk in chunks}
    element_by_id = {
        element.element_id: element
        for page in resolved.structure.pages
        for element in page.elements
    }

    chunk_by_element: dict[str, str] = {}
    for chunk in chunks:
        for element_id in chunk.source_element_ids:
            chunk_by_element.setdefault(element_id, chunk.chunk_id)

    deterministic_exclusions = [chunk.chunk_id for chunk in chunks if _is_navigation_chunk(chunk)]
    deterministic_exclusion_set = set(deterministic_exclusions)
    issues: list[ChunkQualityIssue] = []

    for chunk_id in deterministic_exclusions:
        chunk = chunk_by_id[chunk_id]
        issues.append(ChunkQualityIssue(
            issue_id=_stable_id("quality-navigation", [chunk_id]),
            code="navigation_only",
            severity="review",
            resolution="deterministic_exclude",
            chunk_ids=[chunk_id],
            source_element_ids=chunk.source_element_ids,
            pages=chunk.pages,
            section_path=chunk.section_path,
            message="Navigation-only table-of-contents content can compete with the real section content during retrieval.",
        ))

    # Build parent-child chunk graph from canonical relations.
    parent_to_children: dict[str, set[str]] = defaultdict(set)
    child_to_parents: dict[str, set[str]] = defaultdict(set)
    continuation_adjacency: dict[str, set[str]] = defaultdict(set)

    for relation in resolved.structure.relationships:
        source_chunk = chunk_by_element.get(relation.source_element_id)
        target_chunk = chunk_by_element.get(relation.target_element_id)
        if not source_chunk or not target_chunk or source_chunk == target_chunk:
            continue
        if source_chunk in deterministic_exclusion_set or target_chunk in deterministic_exclusion_set:
            continue
        if relation.type == "parent_of":
            parent_to_children[source_chunk].add(target_chunk)
            child_to_parents[target_chunk].add(source_chunk)
        elif relation.type == "continues":
            continuation_adjacency[source_chunk].add(target_chunk)
            continuation_adjacency[target_chunk].add(source_chunk)

    raw_agent_groups: list[tuple[set[str], set[str]]] = []

    # Use only hierarchy roots and recursively collect descendants. This avoids
    # overlapping parent/child candidates for nested list structures.
    hierarchy_parents = set(parent_to_children)
    hierarchy_roots = sorted(
        [chunk_id for chunk_id in hierarchy_parents if chunk_id not in child_to_parents],
        key=lambda value: index_by_id.get(value, 10**12),
    )
    visited_hierarchy: set[str] = set()
    hierarchy_candidate_count = 0
    for root in hierarchy_roots:
        stack = [root]
        group: set[str] = set()
        while stack:
            current = stack.pop()
            if current in group:
                continue
            group.add(current)
            stack.extend(parent_to_children.get(current, set()))
        group -= deterministic_exclusion_set
        if len(group) < 2:
            continue
        visited_hierarchy |= group
        hierarchy_candidate_count += 1
        raw_agent_groups.append((group, {"hierarchy_dependency"}))

    # Catch any parent graph component that had no clear root because of bad or
    # cyclic input. The integrity gate should normally prevent this, but Stage
    # 5.1 remains defensive rather than silently ignoring the relation.
    for parent, children in parent_to_children.items():
        remaining = ({parent, *children} - visited_hierarchy - deterministic_exclusion_set)
        if len(remaining) >= 2:
            hierarchy_candidate_count += 1
            raw_agent_groups.append((remaining, {"hierarchy_dependency"}))
            visited_hierarchy |= remaining

    # Cross-chunk continuation components need a decision when Stage 5 did not
    # already reconstruct them into one semantic unit.
    seen_continuations: set[str] = set()
    continuation_candidate_count = 0
    for start in sorted(continuation_adjacency, key=lambda value: index_by_id.get(value, 10**12)):
        if start in seen_continuations:
            continue
        stack = [start]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            stack.extend(continuation_adjacency.get(current, set()))
        seen_continuations |= component
        component -= deterministic_exclusion_set
        if len(component) >= 2:
            continuation_candidate_count += 1
            raw_agent_groups.append((component, {"cross_chunk_continuation"}))

    contextual_note_candidate_count = 0
    low_information_candidate_count = 0

    for position, chunk in enumerate(chunks):
        if chunk.chunk_id in deterministic_exclusion_set:
            continue
        source_types = {element_by_id[element_id].type for element_id in chunk.source_element_ids if element_id in element_by_id}
        contextual_note = (
            "footnote" in source_types
            or chunk.semantic_type == "footnote"
            or (
                chunk.semantic_type == "paragraph"
                and chunk.token_count <= 120
                and bool(_CONTEXTUAL_NOTE_RE.match(chunk.content_text))
            )
        )
        if contextual_note:
            previous = next(
                (
                    candidate
                    for candidate in reversed(chunks[:position])
                    if candidate.chunk_id not in deterministic_exclusion_set
                    and (not chunk.section_path or candidate.section_path == chunk.section_path)
                    and (not chunk.pages or not candidate.pages or min(abs(a - b) for a in chunk.pages for b in candidate.pages) <= 1)
                ),
                None,
            )
            if previous is not None and previous.chunk_id != chunk.chunk_id:
                contextual_note_candidate_count += 1
                raw_agent_groups.append(({previous.chunk_id, chunk.chunk_id}, {"contextual_note"}))
                continue

        if (
            chunk.token_count <= 20
            and chunk.semantic_type in _LOW_INFORMATION_TYPES
            and not chunk.section_path
        ):
            low_information_candidate_count += 1
            raw_agent_groups.append(({chunk.chunk_id}, {"low_information_content"}))

    merged_groups = _merge_candidate_groups(raw_agent_groups)
    agent_candidates: list[ChunkAgentCandidate] = []

    for chunk_ids, reasons in merged_groups:
        ordered_ids = sorted(chunk_ids, key=lambda value: index_by_id.get(value, 10**12))
        candidate_chunks = [chunk_by_id[chunk_id] for chunk_id in ordered_ids if chunk_id in chunk_by_id]
        if not candidate_chunks:
            continue
        first_index = min(index_by_id[chunk.chunk_id] for chunk in candidate_chunks)
        last_index = max(index_by_id[chunk.chunk_id] for chunk in candidate_chunks)
        previous_chunk_id = next(
            (
                chunks[index].chunk_id
                for index in range(first_index - 1, -1, -1)
                if chunks[index].chunk_id not in deterministic_exclusion_set and chunks[index].chunk_id not in chunk_ids
            ),
            None,
        )
        next_chunk_id = next(
            (
                chunks[index].chunk_id
                for index in range(last_index + 1, len(chunks))
                if chunks[index].chunk_id not in deterministic_exclusion_set and chunks[index].chunk_id not in chunk_ids
            ),
            None,
        )
        source_element_ids = list(dict.fromkeys(
            element_id
            for chunk in candidate_chunks
            for element_id in chunk.source_element_ids
        ))
        pages = sorted({page for chunk in candidate_chunks for page in chunk.pages})
        section_path = candidate_chunks[0].section_path if all(chunk.section_path == candidate_chunks[0].section_path for chunk in candidate_chunks) else []
        candidate_id = _stable_id("agent-candidate", [*ordered_ids, *sorted(reasons)])
        severity = "high" if "cross_chunk_continuation" in reasons else "review"
        agent_candidates.append(ChunkAgentCandidate(
            candidate_id=candidate_id,
            reason_codes=sorted(reasons),
            severity=severity,
            chunk_ids=ordered_ids,
            source_element_ids=source_element_ids,
            pages=pages,
            section_path=section_path,
            estimated_tokens=sum(chunk.token_count for chunk in candidate_chunks),
            previous_chunk_id=previous_chunk_id,
            next_chunk_id=next_chunk_id,
            preview=_chunk_preview(candidate_chunks),
        ))
        issues.append(ChunkQualityIssue(
            issue_id=_stable_id("quality-agent", [candidate_id]),
            code="agent_candidate",
            severity=severity,
            resolution="agent_review",
            chunk_ids=ordered_ids,
            source_element_ids=source_element_ids,
            pages=pages,
            section_path=section_path,
            message=(
                "Related retrieval units may need regrouping or repeated parent context before indexing."
                if "hierarchy_dependency" in reasons
                else "This retrieval unit needs a local semantic decision before indexing."
            ),
        ))

    agent_candidates.sort(key=lambda item: min(index_by_id.get(chunk_id, 10**12) for chunk_id in item.chunk_ids))
    tiny_chunk_count = sum(chunk.token_count < tiny_chunk_threshold for chunk in chunks)
    candidate_chunk_ids = {chunk_id for candidate in agent_candidates for chunk_id in candidate.chunk_ids}

    summary = ChunkQualitySummary(
        baseline_chunk_count=len(chunks),
        tiny_chunk_count=tiny_chunk_count,
        navigation_chunk_count=len(deterministic_exclusions),
        hierarchy_candidate_count=hierarchy_candidate_count,
        continuation_candidate_count=continuation_candidate_count,
        contextual_note_candidate_count=contextual_note_candidate_count,
        low_information_candidate_count=low_information_candidate_count,
        agent_candidate_count=len(agent_candidates),
        deterministic_exclusion_count=len(deterministic_exclusions),
        candidate_chunk_count=len(candidate_chunk_ids),
    )

    return ChunkQualityReport(
        document_id=baseline.document_id,
        source_chunking_generated_at=baseline.generated_at,
        source_resolved_at=resolved.resolved_at,
        status="review" if issues else "pass",
        tiny_chunk_threshold=tiny_chunk_threshold,
        summary=summary,
        deterministic_exclusion_chunk_ids=deterministic_exclusions,
        issues=issues,
        agent_candidates=agent_candidates,
        generated_at=datetime.now(timezone.utc),
    )
