from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import re
from typing import Iterable

from app.schemas import (
    CanonicalElement,
    ChunkingArtifact,
    ChunkingConfig,
    ChunkingSummary,
    CleaningDecision,
    DeterministicChunkQualityReport,
    DeterministicChunkQualitySignal,
    ResolvedStructureArtifact,
    RetrievalChunk,
    RetrievalCleaningSummary,
    StructuredDocument,
)


class ChunkingNotEligibleError(ValueError):
    """Raised when Stage 5 is requested before the resolved structure is eligible."""


_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_PAGE_NUMBER_RE = re.compile(r"^(?:page\s*)?\d+(?:\s*(?:of|/)\s*\d+)?$", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;:])\s+")
_INTRO_END_RE = re.compile(r"(?::|[–—-])\s*$")
_INTRO_PHRASE_RE = re.compile(
    r"\b(?:the following|as follows|must include|shall include|required to|consists? of|includes?)\s*(?::|[–—-])?\s*$",
    re.IGNORECASE,
)
_CONTEXTUAL_NOTE_RE = re.compile(r"^\s*(\d{1,3})\s+(?:refers?|means?|for|where|note|this|the)\b", re.IGNORECASE)
_NAV_TITLES = {"contents", "table of contents", "index"}


@dataclass
class _Unit:
    semantic_type: str
    content_text: str
    section_id: str | None
    pages: list[int]
    source_element_ids: list[str]
    atomic: bool = False
    context_label: str | None = None
    retrieval_context_text: str = ""
    context_element_ids: list[str] | None = None
    refinement_tags: list[str] | None = None


def estimate_tokens(text: str) -> int:
    """Return a deterministic token *estimate* without a model-specific dependency.

    Stage 5 v1 deliberately does not pretend this is an embedding-model tokenizer.
    The artifact records ``regex_estimate_v1`` so a later indexing stage can switch
    to an exact tokenizer without changing provenance or chunk semantics.
    """

    return len(_TOKEN_RE.findall(text))


def _normalize_text(text: str, *, normalize_whitespace: bool, dehyphenate_line_breaks: bool) -> str:
    value = text.replace("\u00ad", "")
    if dehyphenate_line_breaks:
        # Conservative and opt-in only. Genuine lexical compounds are otherwise
        # safer to preserve than to guess at automatically.
        value = re.sub(
            r"([A-Za-z]{4,})-\s*\n\s*([a-z][A-Za-z]{2,})",
            lambda match: f"{match.group(1)}{match.group(2)}",
            value,
        )
    if normalize_whitespace:
        value = re.sub(r"[ \t\f\v]+", " ", value)
        value = re.sub(r"\s*\n\s*", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        value = value.strip()
    return value


def _preview(text: str, limit: int = 180) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= limit else f"{one_line[: limit - 1].rstrip()}…"


def _flatten_elements(structure: StructuredDocument) -> list[CanonicalElement]:
    return sorted(
        [element for page in structure.pages for element in page.elements],
        key=lambda item: (item.document_order, item.page_number, item.reading_order),
    )


def _margin_repeat_texts(structure: StructuredDocument, config: ChunkingConfig) -> set[str]:
    if not config.cleaning.exclude_repeated_margin_text:
        return set()

    pages_by_text: dict[str, set[int]] = defaultdict(set)
    for page in structure.pages:
        height = max(page.height, 1.0)
        for element in page.elements:
            text = _normalize_text(
                element.text,
                normalize_whitespace=True,
                dehyphenate_line_breaks=False,
            )
            normalized = " ".join(text.lower().split())
            if not normalized or len(normalized) > 220:
                continue
            if element.bbox[1] <= height * 0.12 or element.bbox[3] >= height * 0.88:
                pages_by_text[normalized].add(page.page_number)

    threshold = config.cleaning.repeated_margin_min_pages
    return {text for text, pages in pages_by_text.items() if len(pages) >= threshold}




def _bbox_overlap_ratio(a: list[float], b: list[float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    intersection = (ix1 - ix0) * (iy1 - iy0)
    area_a = max(0.0, (ax1 - ax0) * (ay1 - ay0))
    area_b = max(0.0, (bx1 - bx0) * (by1 - by0))
    smaller = min(area_a, area_b)
    return intersection / smaller if smaller > 0 else 0.0


def _overlapping_duplicate_ids(structure: StructuredDocument, config: ChunkingConfig) -> set[str]:
    if not config.cleaning.deduplicate_overlapping_text:
        return set()
    duplicates: set[str] = set()
    for page in structure.pages:
        by_text: dict[str, list[CanonicalElement]] = defaultdict(list)
        for element in sorted(page.elements, key=lambda item: (item.document_order, item.reading_order)):
            text = _normalize_text(
                element.text,
                normalize_whitespace=True,
                dehyphenate_line_breaks=False,
            )
            key = " ".join(text.lower().split())
            if len(key) < 2:
                continue
            prior = by_text[key]
            if any(_bbox_overlap_ratio(existing.bbox, element.bbox) >= 0.9 for existing in prior):
                duplicates.add(element.element_id)
            else:
                prior.append(element)
    return duplicates


def _navigation_section_ids(structure: StructuredDocument) -> set[str]:
    section_by_id = {section.section_id: section for section in structure.sections}
    navigation_ids: set[str] = set()

    def has_navigation_ancestor(section_id: str | None) -> bool:
        seen: set[str] = set()
        current = section_id
        while current and current not in seen:
            seen.add(current)
            section = section_by_id.get(current)
            if section is None:
                return False
            title = " ".join(section.title.lower().split()).strip(" :.-")
            if title in _NAV_TITLES:
                return True
            current = section.parent_section_id
        return False

    for section in structure.sections:
        if has_navigation_ancestor(section.section_id):
            navigation_ids.add(section.section_id)
    return navigation_ids


def _looks_like_intro(text: str) -> bool:
    value = " ".join(text.split())
    return bool(_INTRO_END_RE.search(value) or _INTRO_PHRASE_RE.search(value))


def _looks_like_contextual_note(text: str) -> tuple[bool, str | None]:
    match = _CONTEXTUAL_NOTE_RE.match(text or "")
    return (bool(match), match.group(1) if match else None)


def _cleaning_decisions(
    structure: StructuredDocument,
    config: ChunkingConfig,
) -> tuple[dict[str, CleaningDecision], dict[str, str], RetrievalCleaningSummary]:
    repeated_margin_texts = _margin_repeat_texts(structure, config)
    overlapping_duplicates = _overlapping_duplicate_ids(structure, config)
    navigation_section_ids = _navigation_section_ids(structure) if config.strategy == "semantic_v2" and config.exclude_navigation_sections else set()
    page_height = {page.page_number: max(page.height, 1.0) for page in structure.pages}
    decisions: dict[str, CleaningDecision] = {}
    normalized_text: dict[str, str] = {}
    normalized_count = 0

    for element in _flatten_elements(structure):
        cleaned = _normalize_text(
            element.text,
            normalize_whitespace=config.cleaning.normalize_whitespace,
            dehyphenate_line_breaks=config.cleaning.dehyphenate_line_breaks,
        )
        normalized_text[element.element_id] = cleaned
        if cleaned != element.text.strip():
            normalized_count += 1

        action = "include"
        reason = "retrieval_content"
        height = page_height.get(element.page_number, 1.0)
        normalized_key = " ".join(cleaned.lower().split())
        near_margin = element.bbox[1] <= height * 0.12 or element.bbox[3] >= height * 0.88

        if not cleaned and not (element.type == "table" and element.table and element.table.cells):
            action = "exclude"
            reason = "empty_content"
        elif element.element_id in overlapping_duplicates:
            action = "exclude"
            reason = "duplicate_overlapping_text"
        elif element.type == "page_header" and config.cleaning.exclude_page_headers:
            action = "exclude"
            reason = "page_header"
        elif element.type == "page_footer" and config.cleaning.exclude_page_footers:
            action = "exclude"
            reason = "page_footer"
        elif (
            config.cleaning.exclude_margin_page_numbers
            and near_margin
            and _PAGE_NUMBER_RE.fullmatch(cleaned.strip())
        ):
            action = "exclude"
            reason = "margin_page_number"
        elif normalized_key in repeated_margin_texts and near_margin:
            action = "exclude"
            reason = "repeated_margin_text"
        elif element.section_id in navigation_section_ids and element.type in {"table", "paragraph", "list_item", "group_header"}:
            action = "exclude"
            reason = "navigation_only"
        elif element.type == "footnote" and not config.cleaning.include_footnotes:
            action = "exclude"
            reason = "footnote_disabled"
        elif element.type == "document_metadata" and not config.cleaning.include_document_metadata:
            action = "exclude"
            reason = "document_metadata_disabled"
        elif element.type == "figure" and not cleaned and not config.cleaning.include_figures_without_text:
            action = "exclude"
            reason = "figure_without_text"
        elif element.type == "section_header":
            action = "context"
            reason = "section_context"

        decisions[element.element_id] = CleaningDecision(
            element_id=element.element_id,
            page_number=element.page_number,
            type=element.type,
            action=action,
            reason=reason,
            text_preview=_preview(cleaned),
        )

    reason_counts = Counter(decision.reason for decision in decisions.values())
    summary = RetrievalCleaningSummary(
        input_element_count=len(decisions),
        included_element_count=sum(decision.action == "include" for decision in decisions.values()),
        context_element_count=sum(decision.action == "context" for decision in decisions.values()),
        excluded_element_count=sum(decision.action == "exclude" for decision in decisions.values()),
        normalized_element_count=normalized_count,
        reason_counts=dict(sorted(reason_counts.items())),
        decisions=list(decisions.values()),
    )
    return decisions, normalized_text, summary


def _section_paths(structure: StructuredDocument) -> dict[str, list[str]]:
    section_by_id = {section.section_id: section for section in structure.sections}
    memo: dict[str, list[str]] = {}

    def resolve(section_id: str, seen: set[str] | None = None) -> list[str]:
        if section_id in memo:
            return memo[section_id]
        section = section_by_id.get(section_id)
        if section is None:
            return []
        visited = set() if seen is None else set(seen)
        if section_id in visited:
            return [section.title]
        visited.add(section_id)
        parent_path = resolve(section.parent_section_id, visited) if section.parent_section_id else []
        path = [*parent_path, section.title]
        memo[section_id] = path
        return path

    for section_id in section_by_id:
        resolve(section_id)
    return memo


def _serialize_table(cells: list[list[str | None]]) -> str:
    rows: list[str] = []
    for row in cells:
        normalized = [" ".join((cell or "").split()).replace("|", "\\|") for cell in row]
        if not any(normalized):
            continue
        rows.append(" | ".join(normalized))
    return "\n".join(rows)


def _collect_pages(element_ids: Iterable[str], element_by_id: dict[str, CanonicalElement]) -> list[int]:
    return sorted({element_by_id[element_id].page_number for element_id in element_ids if element_id in element_by_id})


def _build_semantic_units_v1(
    structure: StructuredDocument,
    decisions: dict[str, CleaningDecision],
    normalized_text: dict[str, str],
) -> list[_Unit]:
    elements = _flatten_elements(structure)
    element_by_id = {element.element_id: element for element in elements}
    consumed: set[str] = set()
    units: list[_Unit] = []

    def available(element_id: str) -> bool:
        decision = decisions.get(element_id)
        return bool(decision and decision.action == "include" and element_id not in consumed)

    # Definitions are a first-class semantic unit. Keep the term and its complete
    # definition together even when they span pages; oversized definitions are
    # split later with the definition term repeated as context.
    for entry in sorted(
        structure.definitions,
        key=lambda item: min(
            [element_by_id[element_id].document_order for element_id in [item.term_element_id, *item.definition_element_ids] if element_id in element_by_id]
            or [10**12]
        ),
    ):
        member_ids = [element_id for element_id in [entry.term_element_id, *entry.definition_element_ids] if element_id and available(element_id)]
        if not member_ids:
            continue
        term = _normalize_text(entry.term, normalize_whitespace=True, dehyphenate_line_breaks=False)
        definition_text = _normalize_text(entry.definition_text, normalize_whitespace=True, dehyphenate_line_breaks=False)
        if not definition_text:
            definition_text = "\n\n".join(normalized_text[element_id] for element_id in member_ids if element_id != entry.term_element_id and normalized_text.get(element_id))
        content = "\n\n".join(part for part in [term, definition_text] if part)
        if not content:
            continue
        consumed.update(member_ids)
        units.append(_Unit(
            semantic_type="definition",
            content_text=content,
            section_id=entry.section_id,
            pages=_collect_pages(member_ids, element_by_id) or list(range(entry.start_page, entry.end_page + 1)),
            source_element_ids=member_ids,
            atomic=True,
            context_label=term or None,
        ))

    # Logical tables are reconstructed from their canonical cell matrix rather
    # than from arbitrary text-block boundaries.
    for table in sorted(structure.tables, key=lambda item: item.start_page):
        member_ids = [element_id for element_id in table.fragment_element_ids if available(element_id)]
        if not member_ids:
            continue
        text = _serialize_table(table.cells)
        if not text:
            text = "\n\n".join(normalized_text[element_id] for element_id in member_ids if normalized_text.get(element_id))
        if not text:
            continue
        consumed.update(member_ids)
        units.append(_Unit(
            semantic_type="table",
            content_text=text,
            section_id=table.section_id,
            pages=_collect_pages(member_ids, element_by_id) or list(range(table.start_page, table.end_page + 1)),
            source_element_ids=member_ids,
            atomic=True,
            context_label="Table",
        ))

    # Figure records combine the figure's meaningful text with captions,
    # introductions, and explanations. Purely visual figures remain excluded by
    # the cleaning policy until image understanding is implemented.
    for figure in sorted(structure.figures, key=lambda item: element_by_id[item.element_id].document_order if item.element_id in element_by_id else 10**12):
        ids = [
            figure.element_id,
            *figure.intro_element_ids,
            *figure.caption_element_ids,
            *figure.explanation_element_ids,
            *figure.source_element_ids,
        ]
        member_ids = []
        for element_id in ids:
            if element_id not in member_ids and available(element_id):
                member_ids.append(element_id)
        if not member_ids:
            continue
        text = "\n\n".join(normalized_text[element_id] for element_id in member_ids if normalized_text.get(element_id))
        if not text:
            continue
        consumed.update(member_ids)
        units.append(_Unit(
            semantic_type="figure",
            content_text=text,
            section_id=figure.section_id,
            pages=_collect_pages(member_ids, element_by_id),
            source_element_ids=member_ids,
            atomic=True,
            context_label="Figure",
        ))

    structural_boundaries = {"section_header", "group_header", "clause", "subclause", "definition_term", "definition_text", "table", "figure"}

    # Clauses/subclauses absorb immediately following prose/list content until the
    # next semantic boundary. This keeps markers/headings from becoming orphaned
    # retrieval chunks while avoiding broad cross-section merges.
    for index, element in enumerate(elements):
        if element.type not in {"clause", "subclause"} or not available(element.element_id):
            continue
        member_ids = [element.element_id]
        for follower in elements[index + 1 :]:
            if follower.type in structural_boundaries:
                break
            if follower.section_id != element.section_id:
                break
            if available(follower.element_id):
                member_ids.append(follower.element_id)
        text = "\n\n".join(normalized_text[element_id] for element_id in member_ids if normalized_text.get(element_id))
        if not text:
            continue
        consumed.update(member_ids)
        units.append(_Unit(
            semantic_type=element.type,
            content_text=text,
            section_id=element.section_id,
            pages=_collect_pages(member_ids, element_by_id),
            source_element_ids=member_ids,
            atomic=True,
            context_label=element.clause_number or element.subclause_marker or None,
        ))

    # Any unconsumed table element that was not represented by a LogicalTable is
    # still preserved deterministically using its element-local cell data.
    for element in elements:
        if element.type != "table" or not available(element.element_id):
            continue
        text = _serialize_table(element.table.cells) if element.table else normalized_text.get(element.element_id, "")
        if not text:
            continue
        consumed.add(element.element_id)
        units.append(_Unit(
            semantic_type="table",
            content_text=text,
            section_id=element.section_id,
            pages=[element.page_number],
            source_element_ids=[element.element_id],
            atomic=True,
            context_label="Table",
        ))

    # Remaining elements are small semantic units. They are packed later only
    # when they share the same section context.
    for element in elements:
        if not available(element.element_id):
            continue
        text = normalized_text.get(element.element_id, "")
        if not text:
            continue
        consumed.add(element.element_id)
        units.append(_Unit(
            semantic_type=element.type,
            content_text=text,
            section_id=element.section_id,
            pages=[element.page_number],
            source_element_ids=[element.element_id],
            atomic=element.type in {"title", "subtitle", "document_metadata", "formula", "footnote"},
        ))

    # Preserve original document order across the heterogeneous semantic units.
    return sorted(
        units,
        key=lambda unit: min(
            (element_by_id[element_id].document_order for element_id in unit.source_element_ids if element_id in element_by_id),
            default=10**12,
        ),
    )



def _refine_semantic_units_v2(
    units: list[_Unit],
    structure: StructuredDocument,
    config: ChunkingConfig,
) -> list[_Unit]:
    """Refine semantic-v1 units using only generic structure signals.

    No domain vocabulary is used here. Decisions are driven by canonical
    hierarchy/continuation relations, section identity, adjacency, punctuation,
    semantic type and token budgets so the same rules apply to unrelated PDFs.
    """

    if not units:
        return []

    elements = _flatten_elements(structure)
    element_by_id = {element.element_id: element for element in elements}
    unit_by_element: dict[str, int] = {}
    for index, unit in enumerate(units):
        for element_id in unit.source_element_ids:
            unit_by_element[element_id] = index

    order_by_unit = {
        index: min(
            (element_by_id[element_id].document_order for element_id in unit.source_element_ids if element_id in element_by_id),
            default=10**12,
        )
        for index, unit in enumerate(units)
    }

    parent_to_children: dict[int, set[int]] = defaultdict(set)
    child_to_parents: dict[int, set[int]] = defaultdict(set)
    continuation: dict[int, set[int]] = defaultdict(set)

    def add_parent(source_id: str, target_id: str) -> None:
        source_unit = unit_by_element.get(source_id)
        target_unit = unit_by_element.get(target_id)
        if source_unit is None or target_unit is None or source_unit == target_unit:
            return
        parent_to_children[source_unit].add(target_unit)
        child_to_parents[target_unit].add(source_unit)

    for relation in structure.relationships:
        source_unit = unit_by_element.get(relation.source_element_id)
        target_unit = unit_by_element.get(relation.target_element_id)
        if source_unit is None or target_unit is None or source_unit == target_unit:
            continue
        if relation.type == "parent_of":
            add_parent(relation.source_element_id, relation.target_element_id)
        elif relation.type == "introduces":
            source_element = element_by_id.get(relation.source_element_id)
            target_element = element_by_id.get(relation.target_element_id)
            semantic_dependency_types = {"group_header", "clause", "subclause", "list_item"}
            if (
                source_element is not None
                and target_element is not None
                and source_element.type in semantic_dependency_types
                and target_element.type in semantic_dependency_types
            ):
                add_parent(relation.source_element_id, relation.target_element_id)
        elif relation.type == "continues" and config.preserve_cross_page_continuations:
            continuation[source_unit].add(target_unit)
            continuation[target_unit].add(source_unit)

    # Clause records are a second, format-independent hierarchy signal. They
    # recover dependency grouping when the explicit relation list is incomplete.
    clause_element_by_id = {clause.clause_id: clause.element_id for clause in structure.clauses}
    for clause in structure.clauses:
        if clause.parent_clause_id:
            parent_element_id = clause_element_by_id.get(clause.parent_clause_id)
            if parent_element_id:
                add_parent(parent_element_id, clause.element_id)

    consumed: set[int] = set()
    refined: list[_Unit] = []

    def combine(group_indices: list[int], *, semantic_type: str | None = None, context_label: str | None = None,
                retrieval_context_text: str = "", context_element_ids: list[str] | None = None,
                tags: list[str] | None = None) -> _Unit:
        ordered = sorted(dict.fromkeys(group_indices), key=lambda idx: order_by_unit[idx])
        group_units = [units[idx] for idx in ordered]
        return _Unit(
            semantic_type=semantic_type or (group_units[0].semantic_type if len({u.semantic_type for u in group_units}) == 1 else "mixed"),
            content_text="\n\n".join(u.content_text for u in group_units if u.content_text),
            section_id=group_units[0].section_id,
            pages=sorted({page for u in group_units for page in u.pages}),
            source_element_ids=list(dict.fromkeys(element_id for u in group_units for element_id in u.source_element_ids)),
            atomic=True,
            context_label=context_label,
            retrieval_context_text=retrieval_context_text,
            context_element_ids=list(context_element_ids or []),
            refinement_tags=list(dict.fromkeys(tags or [])),
        )

    # 1) Parent/dependent-child components. A page boundary is irrelevant here;
    # canonical relationships define the semantic dependency.
    if config.group_dependent_children:
        roots = sorted(
            [idx for idx in parent_to_children if idx not in child_to_parents],
            key=lambda idx: order_by_unit[idx],
        )
        seen_hierarchy: set[int] = set()
        for root in roots:
            if root in consumed:
                continue
            stack = [root]
            component: set[int] = set()
            while stack:
                current = stack.pop()
                if current in component:
                    continue
                component.add(current)
                stack.extend(parent_to_children.get(current, set()))
                # Continuations of a hierarchy member belong to the same logical
                # dependency component before size enforcement.
                stack.extend(continuation.get(current, set()))
            component -= consumed
            if len(component) < 2:
                continue
            seen_hierarchy |= component
            ordered = sorted(component, key=lambda idx: order_by_unit[idx])
            root_unit = units[root]
            total_text = "\n\n".join(units[idx].content_text for idx in ordered)
            if estimate_tokens(total_text) <= config.max_tokens:
                refined.append(combine(
                    ordered,
                    semantic_type=root_unit.semantic_type,
                    context_label=root_unit.context_label,
                    tags=["dependency_group"] + (["continuation_merge"] if any(continuation.get(idx) for idx in ordered) else []),
                ))
                consumed |= component
                continue

            # Oversized dependency component: split only between semantic child
            # units and repeat the root as retrieval context on later groups.
            root_tokens = estimate_tokens(root_unit.content_text)
            groups: list[list[int]] = []
            current: list[int] = [root]
            current_tokens = root_tokens
            for idx in ordered:
                if idx == root:
                    continue
                child_tokens = estimate_tokens(units[idx].content_text)
                separator = 1 if current else 0
                target = config.target_tokens
                if len(current) > 1 and current_tokens + child_tokens + separator > target:
                    groups.append(current)
                    current = []
                    current_tokens = 0
                if not current and groups:
                    # Later groups carry root as context, not duplicated source.
                    current = [idx]
                    current_tokens = child_tokens
                else:
                    current.append(idx)
                    current_tokens += child_tokens + separator
            if current:
                groups.append(current)

            for group_number, group in enumerate(groups):
                if group_number == 0:
                    refined.append(combine(
                        group,
                        semantic_type=root_unit.semantic_type,
                        context_label=root_unit.context_label,
                        tags=["dependency_group"],
                    ))
                else:
                    context_text = ""
                    context_ids: list[str] = []
                    if config.attach_parent_context_on_split:
                        context_text = f"Parent context:\n{root_unit.content_text}"
                        context_ids = list(root_unit.source_element_ids)
                    refined.append(combine(
                        group,
                        semantic_type=units[group[0]].semantic_type,
                        retrieval_context_text=context_text,
                        context_element_ids=context_ids,
                        tags=["dependency_group", "parent_context"],
                    ))
            consumed |= component

        # Defensive cycle/no-root handling.
        for parent, children in sorted(parent_to_children.items(), key=lambda item: order_by_unit[item[0]]):
            component = ({parent, *children} - consumed)
            if len(component) >= 2:
                ordered = sorted(component, key=lambda idx: order_by_unit[idx])
                refined.append(combine(ordered, tags=["dependency_group"]))
                consumed |= component

    # 2) Explicit continuation components that are not already absorbed into a
    # hierarchy group. These rules work across pages and across document genres.
    seen_continuations: set[int] = set()
    for start in sorted(continuation, key=lambda idx: order_by_unit[idx]):
        if start in consumed or start in seen_continuations:
            continue
        stack = [start]
        component: set[int] = set()
        while stack:
            current = stack.pop()
            if current in component or current in consumed:
                continue
            component.add(current)
            stack.extend(continuation.get(current, set()))
        seen_continuations |= component
        if len(component) >= 2:
            ordered = sorted(component, key=lambda idx: order_by_unit[idx])
            refined.append(combine(
                ordered,
                semantic_type=units[ordered[0]].semantic_type,
                context_label=units[ordered[0]].context_label,
                tags=["continuation_merge"],
            ))
            consumed |= component

    # Work with the untouched units in document order for note attachment and
    # conservative short-sibling packing.
    remaining = [idx for idx in sorted(range(len(units)), key=lambda idx: order_by_unit[idx]) if idx not in consumed]

    # 3) Contextual note / footnote attachment. Numbered paragraph notes are only
    # attached when the preceding unit contains a matching inline marker; typed
    # footnotes rely on proximity and section identity.
    note_consumed: set[int] = set()
    if config.attach_contextual_notes:
        for pos, idx in enumerate(remaining):
            if idx in note_consumed:
                continue
            unit = units[idx]
            is_numbered_note, marker = _looks_like_contextual_note(unit.content_text)
            is_footnote = unit.semantic_type == "footnote"
            if not is_footnote and not is_numbered_note:
                continue
            previous_idx = next((remaining[p] for p in range(pos - 1, -1, -1) if remaining[p] not in note_consumed), None)
            if previous_idx is None:
                continue
            previous = units[previous_idx]
            if previous.section_id != unit.section_id:
                continue
            if previous.pages and unit.pages and min(abs(a - b) for a in previous.pages for b in unit.pages) > 1:
                continue
            marker_matches = True
            if marker and not is_footnote:
                marker_matches = bool(re.search(rf"(?:[A-Za-z)\]]){re.escape(marker)}\b", previous.content_text))
            if not marker_matches:
                continue
            combined_text = f"{previous.content_text}\n\nNote:\n{unit.content_text}"
            if estimate_tokens(combined_text) > config.max_tokens:
                continue
            refined.append(_Unit(
                semantic_type=previous.semantic_type,
                content_text=combined_text,
                section_id=previous.section_id,
                pages=sorted(set(previous.pages + unit.pages)),
                source_element_ids=list(dict.fromkeys(previous.source_element_ids + unit.source_element_ids)),
                atomic=True,
                context_label=previous.context_label,
                refinement_tags=["note_attachment"],
            ))
            note_consumed.update({previous_idx, idx})

    remaining = [idx for idx in remaining if idx not in note_consumed]

    # 4) Conservative sibling packing. Only short standalone clauses in the same
    # section are packed; dependent subclauses are never guessed into siblings.
    if config.pack_short_sibling_clauses:
        cursor = 0
        while cursor < len(remaining):
            idx = remaining[cursor]
            unit = units[idx]
            if unit.semantic_type != "clause" or estimate_tokens(unit.content_text) >= config.soft_min_tokens or _looks_like_intro(unit.content_text):
                refined.append(unit)
                cursor += 1
                continue
            group = [idx]
            tokens = estimate_tokens(unit.content_text)
            next_cursor = cursor + 1
            while next_cursor < len(remaining):
                nxt = remaining[next_cursor]
                nxt_unit = units[nxt]
                if (
                    nxt_unit.semantic_type != "clause"
                    or nxt_unit.section_id != unit.section_id
                    or estimate_tokens(nxt_unit.content_text) >= config.soft_min_tokens
                    or _looks_like_intro(nxt_unit.content_text)
                ):
                    break
                candidate_tokens = tokens + estimate_tokens(nxt_unit.content_text) + 1
                if candidate_tokens > config.target_tokens:
                    break
                group.append(nxt)
                tokens = candidate_tokens
                next_cursor += 1
            if len(group) > 1:
                refined.append(combine(group, semantic_type="clause", tags=["short_sibling_pack"]))
            else:
                refined.append(unit)
            cursor = next_cursor if len(group) > 1 else cursor + 1
    else:
        refined.extend(units[idx] for idx in remaining)

    return sorted(
        refined,
        key=lambda unit: min(
            (element_by_id[element_id].document_order for element_id in unit.source_element_ids if element_id in element_by_id),
            default=10**12,
        ),
    )


def _build_semantic_units(
    structure: StructuredDocument,
    decisions: dict[str, CleaningDecision],
    normalized_text: dict[str, str],
    config: ChunkingConfig,
) -> list[_Unit]:
    baseline = _build_semantic_units_v1(structure, decisions, normalized_text)
    if config.strategy == "semantic_v1":
        return baseline
    return _refine_semantic_units_v2(baseline, structure, config)

def _context_for_unit(
    unit: _Unit,
    structure: StructuredDocument,
    section_paths: dict[str, list[str]],
    config: ChunkingConfig,
) -> tuple[str, list[str]]:
    path = section_paths.get(unit.section_id or "", [])
    lines: list[str] = []
    if config.preserve_section_context and path:
        lines.append(f"Section: {' > '.join(path)}")
    if unit.semantic_type == "definition" and unit.context_label:
        lines.append(f"Definition: {unit.context_label}")
    elif unit.semantic_type in {"clause", "subclause"} and unit.context_label:
        lines.append(f"Clause: {unit.context_label}")
    if unit.retrieval_context_text:
        lines.append(unit.retrieval_context_text)
    return "\n".join(lines), path


def _merge_generic_units(units: list[_Unit], config: ChunkingConfig) -> list[_Unit]:
    """Pack non-atomic adjacent units within a section up to target size."""

    merged: list[_Unit] = []
    current: list[_Unit] = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        semantic_types = {unit.semantic_type for unit in current}
        merged.append(_Unit(
            semantic_type=next(iter(semantic_types)) if len(semantic_types) == 1 else "mixed",
            content_text="\n\n".join(unit.content_text for unit in current if unit.content_text),
            section_id=current[0].section_id,
            pages=sorted({page for unit in current for page in unit.pages}),
            source_element_ids=[element_id for unit in current for element_id in unit.source_element_ids],
            atomic=False,
        ))
        current = []

    for unit in units:
        if unit.atomic:
            flush()
            merged.append(unit)
            continue
        if current and unit.section_id != current[0].section_id:
            flush()
        candidate = "\n\n".join([*(item.content_text for item in current), unit.content_text])
        if current and estimate_tokens(candidate) > config.target_tokens:
            flush()
        current.append(unit)
    flush()
    return merged


def _split_long_piece(piece: str, budget: int) -> list[str]:
    words = piece.split()
    if not words:
        return []
    parts: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if current and estimate_tokens(candidate) > budget:
            parts.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        parts.append(" ".join(current))
    return parts


def _split_content(content: str, *, budget: int, overlap_tokens: int) -> list[str]:
    if estimate_tokens(content) <= budget:
        return [content]

    logical_parts: list[str] = []
    for paragraph in [part.strip() for part in content.split("\n\n") if part.strip()]:
        if estimate_tokens(paragraph) <= budget:
            logical_parts.append(paragraph)
            continue
        sentences = [part.strip() for part in _SENTENCE_SPLIT_RE.split(paragraph) if part.strip()]
        if len(sentences) <= 1:
            logical_parts.extend(_split_long_piece(paragraph, budget))
            continue
        for sentence in sentences:
            if estimate_tokens(sentence) <= budget:
                logical_parts.append(sentence)
            else:
                logical_parts.extend(_split_long_piece(sentence, budget))

    chunks: list[str] = []
    current = ""
    for part in logical_parts:
        candidate = f"{current}\n\n{part}".strip() if current else part
        if current and estimate_tokens(candidate) > budget:
            chunks.append(current)
            overlap_words: list[str] = []
            if overlap_tokens > 0:
                words = current.split()
                for word in reversed(words):
                    trial = " ".join(reversed([word, *overlap_words]))
                    if estimate_tokens(trial) > overlap_tokens:
                        break
                    overlap_words.insert(0, word)
            current = " ".join(overlap_words + [part]).strip()
            if estimate_tokens(current) > budget:
                # Overlap is advisory; never let it violate the hard max.
                current = part
        else:
            current = candidate
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk.strip()]



def _split_table_rows(content: str, *, budget: int, target: int) -> list[tuple[str, str]]:
    """Split a serialized table on row boundaries and repeat its header as context.

    The first non-empty row is treated as the header. A single pathological row
    that exceeds the hard budget is split as a last resort; normal rows are never
    cut across chunks.
    """
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines or estimate_tokens(content) <= budget:
        return [(content, "")]
    header = lines[0]
    rows = lines[1:]
    if not rows:
        return [(part, "") for part in _split_long_piece(content, budget)]

    header_context = f"Table header:\n{header}"
    header_tokens = estimate_tokens(header_context)
    row_budget = max(20, budget - header_tokens - 1)
    desired = max(20, min(target - header_tokens - 1, row_budget))
    groups: list[list[str]] = []
    current: list[str] = []
    current_tokens = 0

    for row in rows:
        row_tokens = estimate_tokens(row)
        if row_tokens > row_budget:
            if current:
                groups.append(current)
                current = []
                current_tokens = 0
            for piece in _split_long_piece(row, row_budget):
                groups.append([piece])
            continue
        if current and current_tokens + row_tokens + 1 > desired:
            groups.append(current)
            current = []
            current_tokens = 0
        current.append(row)
        current_tokens += row_tokens + (1 if current_tokens else 0)
    if current:
        groups.append(current)

    result: list[tuple[str, str]] = []
    for index, group in enumerate(groups):
        if index == 0:
            result.append(("\n".join([header, *group]), ""))
        else:
            result.append(("\n".join(group), header_context))
    return result

def _provenance_for(
    source_ids: list[str],
    structure: StructuredDocument,
    context_ids: list[str] | None = None,
) -> tuple[list[str], list[str], list[str], list[str]]:
    element_by_id = {element.element_id: element for page in structure.pages for element in page.elements}
    span_ids: list[str] = []
    block_ids: list[str] = []
    table_ids: list[str] = []
    for element_id in source_ids:
        element = element_by_id.get(element_id)
        if element is None:
            continue
        for value in element.source.stage3_span_ids:
            if value not in span_ids:
                span_ids.append(value)
        for value in element.source.stage3_block_ids:
            if value not in block_ids:
                block_ids.append(value)
        for value in element.source.stage3_table_ids:
            if value not in table_ids:
                table_ids.append(value)

    provenance_set = set(source_ids) | set(context_ids or [])
    relationship_ids = [
        relation.relation_id
        for relation in structure.relationships
        if relation.source_element_id in provenance_set or relation.target_element_id in provenance_set
    ]
    return span_ids, block_ids, table_ids, relationship_ids


def _chunk_id(document_id: str, index: int, semantic_type: str, text: str, source_ids: list[str]) -> str:
    digest_source = "\n".join([semantic_type, *source_ids, text])
    digest = sha256(digest_source.encode("utf-8")).hexdigest()[:10]
    return f"{document_id}-c{index:04d}-{digest}"


def _materialize_chunks(
    structure: StructuredDocument,
    units: list[_Unit],
    config: ChunkingConfig,
) -> list[RetrievalChunk]:
    section_paths = _section_paths(structure)
    packed_units = _merge_generic_units(units, config)
    drafts: list[dict] = []

    for unit in packed_units:
        context_text, section_path = _context_for_unit(unit, structure, section_paths, config)
        context_tokens = estimate_tokens(context_text)
        budget = max(40, config.max_tokens - context_tokens - (1 if context_text else 0))
        if unit.semantic_type == "table" and config.strategy == "semantic_v2" and config.row_aware_table_splitting:
            part_specs = _split_table_rows(
                unit.content_text,
                budget=budget,
                target=min(config.target_tokens, budget),
            )
        else:
            part_specs = [
                (part, "")
                for part in _split_content(
                    unit.content_text,
                    budget=budget,
                    overlap_tokens=min(config.overlap_tokens, max(0, budget // 3)),
                )
            ]
        total = len(part_specs)
        for part_number, (part, extra_context) in enumerate(part_specs, start=1):
            combined_context = "\n".join(value for value in [context_text, extra_context] if value).strip()
            text = f"{combined_context}\n\n{part}".strip() if combined_context else part.strip()
            # If an unusually long section/parent/table context consumes the
            # token budget, drop repeated context rather than violate hard max.
            if estimate_tokens(text) > config.max_tokens and combined_context:
                text = part.strip()
                context_for_chunk = ""
            else:
                context_for_chunk = combined_context
            tags = list(unit.refinement_tags or [])
            if extra_context and "table_row_split" not in tags:
                tags.append("table_row_split")
            drafts.append({
                "semantic_type": unit.semantic_type,
                "text": text,
                "content_text": part.strip(),
                "context_text": context_for_chunk,
                "pages": sorted(set(unit.pages)),
                "section_path": section_path,
                "source_element_ids": list(dict.fromkeys(unit.source_element_ids)),
                "context_element_ids": list(dict.fromkeys(unit.context_element_ids or [])),
                "refinement_tags": tags,
                "split_part": part_number if total > 1 else None,
                "split_total": total if total > 1 else None,
            })

    chunks: list[RetrievalChunk] = []
    for index, draft in enumerate(drafts):
        source_ids = draft["source_element_ids"]
        context_ids = draft.get("context_element_ids", [])
        span_ids, block_ids, table_ids, relationship_ids = _provenance_for(source_ids, structure, context_ids)
        text = draft["text"]
        token_count = estimate_tokens(text)
        if token_count <= 0:
            continue
        if token_count > config.max_tokens:
            # Defensive invariant: _split_content should already enforce this.
            raise ValueError(
                f"Chunk generation exceeded max_tokens ({token_count} > {config.max_tokens}) for source elements {source_ids}."
            )
        chunks.append(RetrievalChunk(
            chunk_id=_chunk_id(structure.document_id, index, draft["semantic_type"], text, source_ids),
            chunk_index=index,
            semantic_type=draft["semantic_type"],
            text=text,
            content_text=draft["content_text"],
            context_text=draft["context_text"],
            token_count=token_count,
            pages=draft["pages"],
            section_path=draft["section_path"],
            source_element_ids=source_ids,
            context_element_ids=context_ids,
            refinement_tags=draft.get("refinement_tags", []),
            source_span_ids=span_ids,
            source_block_ids=block_ids,
            source_table_ids=table_ids,
            relationship_ids=relationship_ids,
            split_part=draft["split_part"],
            split_total=draft["split_total"],
        ))
    return chunks



def _build_deterministic_quality_report(
    chunks: list[RetrievalChunk],
    structure: StructuredDocument,
    config: ChunkingConfig,
) -> DeterministicChunkQualityReport:
    element_by_id = {element.element_id: element for page in structure.pages for element in page.elements}
    parent_by_child: dict[str, str] = {}
    children_by_parent: dict[str, set[str]] = defaultdict(set)
    for relation in structure.relationships:
        if relation.type == "parent_of":
            parent_by_child[relation.target_element_id] = relation.source_element_id
            children_by_parent[relation.source_element_id].add(relation.target_element_id)
        elif relation.type == "introduces":
            source = element_by_id.get(relation.source_element_id)
            target = element_by_id.get(relation.target_element_id)
            semantic_dependency_types = {"group_header", "clause", "subclause", "list_item"}
            if source and target and source.type in semantic_dependency_types and target.type in semantic_dependency_types:
                parent_by_child[relation.target_element_id] = relation.source_element_id
                children_by_parent[relation.source_element_id].add(relation.target_element_id)
    clause_element_by_id = {clause.clause_id: clause.element_id for clause in structure.clauses}
    for clause in structure.clauses:
        if clause.parent_clause_id and clause.parent_clause_id in clause_element_by_id:
            parent_id = clause_element_by_id[clause.parent_clause_id]
            parent_by_child.setdefault(clause.element_id, parent_id)
            children_by_parent[parent_id].add(clause.element_id)

    navigation_ids = _navigation_section_ids(structure)
    signals: list[DeterministicChunkQualitySignal] = []
    orphan_count = 0
    dangling_count = 0
    nav_count = 0

    for chunk in chunks:
        present = set(chunk.source_element_ids) | set(chunk.context_element_ids)
        orphan = False
        for element_id in chunk.source_element_ids:
            parent_id = parent_by_child.get(element_id)
            if parent_id and parent_id not in present:
                orphan = True
                break
        if orphan:
            orphan_count += 1
            signals.append(DeterministicChunkQualitySignal(
                code="orphan_child",
                chunk_id=chunk.chunk_id,
                message="A dependent child is retrievable without its canonical parent context.",
            ))

        dangling = False
        for parent_id in chunk.source_element_ids:
            children = children_by_parent.get(parent_id, set())
            element = element_by_id.get(parent_id)
            if children and element and _looks_like_intro(element.text) and not (children & present):
                dangling = True
                break
        if dangling:
            dangling_count += 1
            signals.append(DeterministicChunkQualitySignal(
                code="dangling_intro",
                chunk_id=chunk.chunk_id,
                message="An introductory parent ends with an open dependency but its children are not present.",
            ))

        if any((element_by_id.get(element_id) and element_by_id[element_id].section_id in navigation_ids) for element_id in chunk.source_element_ids):
            nav_count += 1
            signals.append(DeterministicChunkQualitySignal(
                code="navigation_content",
                chunk_id=chunk.chunk_id,
                message="Navigation-only content remains in the retrieval artifact.",
            ))

    tiny_count = sum(
        chunk.token_count < config.soft_min_tokens and chunk.semantic_type not in {"definition", "table"}
        for chunk in chunks
    )
    hard_issue_count = orphan_count + dangling_count + nav_count
    return DeterministicChunkQualityReport(
        status="review" if hard_issue_count else "pass",
        soft_min_tokens=config.soft_min_tokens,
        tiny_chunk_count=tiny_count,
        orphan_child_count=orphan_count,
        dangling_intro_count=dangling_count,
        navigation_chunk_count=nav_count,
        context_attached_chunk_count=sum(bool(chunk.context_element_ids) for chunk in chunks),
        dependency_group_chunk_count=sum("dependency_group" in chunk.refinement_tags for chunk in chunks),
        continuation_merge_chunk_count=sum("continuation_merge" in chunk.refinement_tags for chunk in chunks),
        sibling_pack_chunk_count=sum("short_sibling_pack" in chunk.refinement_tags for chunk in chunks),
        table_split_chunk_count=sum("table_row_split" in chunk.refinement_tags for chunk in chunks),
        note_attachment_chunk_count=sum("note_attachment" in chunk.refinement_tags for chunk in chunks),
        signals=signals,
    )

def build_chunking_artifact(
    *,
    resolved: ResolvedStructureArtifact,
    config: ChunkingConfig | None = None,
) -> ChunkingArtifact:
    config = config or ChunkingConfig()
    if resolved.integrity.status != "pass" or not resolved.review.stage5_eligible:
        raise ChunkingNotEligibleError(
            "Stage 5 requires a resolved Stage 4.5 artifact with passing structural integrity."
        )

    structure = resolved.structure
    decisions, normalized_text, cleaning_summary = _cleaning_decisions(structure, config)
    units = _build_semantic_units(structure, decisions, normalized_text, config)
    chunks = _materialize_chunks(structure, units, config)
    quality_report = _build_deterministic_quality_report(chunks, structure, config)

    warnings: list[str] = []
    if not chunks:
        warnings.append("No retrieval chunks were produced after cleaning and semantic grouping.")
    if config.cleaning.dehyphenate_line_breaks:
        warnings.append("Line-break dehyphenation is enabled; review affected text because lexical hyphens can be ambiguous.")
    warnings.append(
        "Token counts are deterministic estimates (regex_estimate_v1), not model-specific tokenizer counts."
    )

    token_counts = [chunk.token_count for chunk in chunks]
    type_counts = Counter(chunk.semantic_type for chunk in chunks)
    pages_covered = sorted({page for chunk in chunks for page in chunk.pages})
    summary = ChunkingSummary(
        chunk_count=len(chunks),
        estimated_token_count=sum(token_counts),
        min_chunk_tokens=min(token_counts, default=0),
        max_chunk_tokens=max(token_counts, default=0),
        average_chunk_tokens=round(sum(token_counts) / len(token_counts), 2) if token_counts else 0.0,
        semantic_type_counts=dict(sorted(type_counts.items())),
        pages_covered=pages_covered,
    )

    return ChunkingArtifact(
        document_id=resolved.document_id,
        source_sha256=resolved.source_sha256,
        source_resolved_schema_version=resolved.schema_version,
        source_resolved_at=resolved.resolved_at,
        base_structured_at=resolved.base_structured_at,
        strategy_version="semantic-v2" if config.strategy == "semantic_v2" else "semantic-v1",
        config=config,
        cleaning=cleaning_summary,
        summary=summary,
        quality=quality_report,
        chunks=chunks,
        warnings=warnings,
        generated_at=datetime.now(timezone.utc),
    )
