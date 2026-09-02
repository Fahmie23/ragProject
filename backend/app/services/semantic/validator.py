from __future__ import annotations

from dataclasses import dataclass, field
import re

from app.schemas import CanonicalElement, SectionRecord, StructuralRelation
from app.services.semantic.patterns import ends_complete_sentence, is_callout_heading


_ENUMERATED_PREFIX_RE = re.compile(r"^\s*(?:\([A-Za-z0-9ivxlcdmIVXLCDM]+\)|[A-Za-z0-9]+[.)])\s*")
_APPENDIX_LABEL_RE = re.compile(r"^\s*APPENDIX\s+[A-Z0-9IVXLC]+\s*$", re.IGNORECASE)
_NUMBERED_HEADING_RE = re.compile(r"^\s*(?:section\s+|chapter\s+)?(\d+(?:\.\d+){0,5})(?:[.)])?(?=\s|[A-Za-z])", re.IGNORECASE)
_NUMBERED_CLAUSE_RE = re.compile(r"^\s*(\d+(?:\.\d+){1,6})(?=\s|[A-Za-z])", re.IGNORECASE)


def _looks_like_form_field_block(text: str) -> bool:
    normalized = "\n".join(line.strip() for line in (text or "").splitlines() if line.strip())
    if not normalized:
        return False
    # Form sections commonly use several label/value rows ending in colons.
    # Treat that as structured form content rather than prose continuation.
    colon_count = normalized.count(":")
    lines = normalized.splitlines()
    return colon_count >= 2 or sum(1 for line in lines if line.rstrip().endswith(":")) >= 2


@dataclass
class SemanticValidationResult:
    warnings: list[str] = field(default_factory=list)
    low_confidence_element_ids: list[str] = field(default_factory=list)
    orphan_group_header_ids: list[str] = field(default_factory=list)
    orphan_list_item_ids: list[str] = field(default_factory=list)
    empty_section_scope_ids: list[str] = field(default_factory=list)
    suspicious_continuation_relation_ids: list[str] = field(default_factory=list)
    detached_clause_tail_ids: list[str] = field(default_factory=list)
    style_split_continuation_ids: list[str] = field(default_factory=list)
    redundant_appendix_title_section_ids: list[str] = field(default_factory=list)
    numbered_section_parent_mismatch_ids: list[str] = field(default_factory=list)
    clause_section_mismatch_ids: list[str] = field(default_factory=list)
    callout_scope_leak_relation_ids: list[str] = field(default_factory=list)


def validate_semantic_structure(
    *,
    elements: list[CanonicalElement],
    sections: list[SectionRecord],
    relationships: list[StructuralRelation],
    low_confidence_threshold: float = 0.65,
) -> SemanticValidationResult:
    """Validate semantic-v2 invariants without inventing repairs.

    This validator is advisory at automatic Stage 4. Blocking integrity remains
    the responsibility of the Stage 4.5 relationship validator. The purpose
    here is to surface semantic ambiguity for review while keeping automatic
    reconstruction deterministic and conservative.
    """
    result = SemanticValidationResult()
    element_by_id = {element.element_id: element for element in elements}
    section_element_ids = {section.element_id for section in sections}
    section_by_id = {section.section_id: section for section in sections}

    def section_number(section: SectionRecord) -> str | None:
        match = _NUMBERED_HEADING_RE.match(" ".join((section.title or "").split()))
        return match.group(1) if match else None

    def section_is_same_or_descendant(section_id: str | None, ancestor_id: str) -> bool:
        """Return True when section_id is ancestor_id or nested beneath it.

        A numbered clause can legitimately live inside an unnumbered local
        topic section nested below its matching numbered outline section.  The
        validator therefore checks semantic ancestry rather than requiring the
        clause's immediate section_id to equal the numbered section exactly.
        """
        current = section_id
        seen: set[str] = set()
        while current and current not in seen:
            if current == ancestor_id:
                return True
            seen.add(current)
            section = section_by_id.get(current)
            current = section.parent_section_id if section is not None else None
        return False

    for element in elements:
        classification = element.classification
        if classification is not None and classification.confidence < low_confidence_threshold:
            result.low_confidence_element_ids.append(element.element_id)
        if element.type == "group_header" and element.element_id in section_element_ids:
            result.warnings.append(
                f"Semantic invariant: group_header {element.element_id} must not create a SectionRecord."
            )

    semantic_edges = [
        relation for relation in relationships
        if relation.type == "introduces"
        and relation.source_element_id in element_by_id
        and relation.target_element_id in element_by_id
    ]
    incoming_introduces = {relation.target_element_id for relation in semantic_edges}
    outgoing_introduces = {relation.source_element_id for relation in semantic_edges}
    incoming_parent = {
        relation.target_element_id
        for relation in relationships
        if relation.type == "parent_of" and relation.target_element_id in element_by_id
    }
    appendix_title_sources: set[str] = set()
    continuation_members: set[str] = set()
    for relation in relationships:
        if relation.type == "continues":
            continuation_members.add(relation.source_element_id)
            continuation_members.add(relation.target_element_id)
        if relation.type != "belongs_to":
            continue
        source = element_by_id.get(relation.source_element_id)
        target = element_by_id.get(relation.target_element_id)
        if source is None or target is None or source.type != "group_header":
            continue
        target_text = " ".join((target.text or "").split()).strip()
        if _APPENDIX_LABEL_RE.fullmatch(target_text):
            appendix_title_sources.add(source.element_id)

    for element in elements:
        if (
            element.type == "group_header"
            and element.element_id not in incoming_introduces
            and element.element_id not in outgoing_introduces
            and element.element_id not in appendix_title_sources
        ):
            result.orphan_group_header_ids.append(element.element_id)

        # A sequence-resolved enumerated list item normally needs an explicit
        # semantic parent.  Missing ownership is not always invalid, but it is a
        # useful review signal because Stage 5 otherwise receives a dependent
        # fragment with no structural context.
        if (
            element.type == "list_item"
            and element.role_source == "semantic_list_sequence"
            and _ENUMERATED_PREFIX_RE.match(element.text or "")
            and element.element_id not in incoming_introduces
            and element.element_id not in incoming_parent
        ):
            result.orphan_list_item_ids.append(element.element_id)


    # Detect unnumbered prose immediately after a list/subclause run that looks
    # like it resumes the active parent clause but has no structural owner.
    belongs_to_sources = {
        relation.source_element_id
        for relation in relationships
        if relation.type == "belongs_to"
    }
    ordered = [
        item for item in sorted(elements, key=lambda value: value.document_order)
        if item.type not in {"page_header", "page_footer", "footnote", "caption", "document_metadata", "title", "subtitle"}
        and item.text.strip()
    ]
    for index, element in enumerate(ordered):
        if (
            index == 0
            or element.type != "paragraph"
            or element.element_id in belongs_to_sources
            or element.element_id in continuation_members
        ):
            continue
        previous = ordered[index - 1]
        normalized = " ".join(element.text.split()).strip()
        if previous.type in {"subclause", "list_item"} and normalized[:1].islower():
            result.detached_clause_tail_ids.append(element.element_id)

    # A heading and following paragraph that share one Stage-3 block can be a
    # style-only split. The continuity resolver should normally remove these;
    # keep a narrow validator check as a regression alarm.
    for left, right in zip(ordered, ordered[1:]):
        if left.type != "section_header" or right.type != "paragraph" or left.page_number != right.page_number:
            continue
        shared_blocks = set(left.source.stage3_block_ids) & set(right.source.stage3_block_ids)
        gap = float(right.bbox[1]) - float(left.bbox[3])
        left_text = " ".join((left.text or "").split()).strip()
        if left_text.endswith(":") or _looks_like_form_field_block(right.text):
            continue
        if shared_blocks and -1.0 <= gap <= 10.0 and left.heading_level_source in {"font_rank", "unknown", None}:
            result.style_split_continuation_ids.append(left.element_id)


    # Appendix titles are represented by AppendixRecord/title belongs_to edges.
    # If such a title still exists as a SectionRecord, the outline contains a
    # duplicate structural node and should be reviewed.
    for relation in relationships:
        if relation.type != "belongs_to":
            continue
        source = element_by_id.get(relation.source_element_id)
        target = element_by_id.get(relation.target_element_id)
        if source is None or target is None:
            continue
        if not _APPENDIX_LABEL_RE.fullmatch(" ".join((target.text or "").split()).strip()):
            continue
        if source.type == "section_header" and source.element_id in section_element_ids:
            result.redundant_appendix_title_section_ids.append(source.element_id)

    # Numbering is a semantic invariant for structured regulatory/policy prose.
    # A dotted section such as 7.3 should attach to the nearest preceding 7
    # section in the same active major region whenever that explicit parent
    # exists.  This is an advisory validator check, not a repair.
    latest_numbered: dict[str, SectionRecord] = {}
    for section in sections:
        number = section_number(section)
        if number:
            parts = number.split(".")
            if len(parts) > 1:
                expected_parent_number = ".".join(parts[:-1])
                expected_parent = latest_numbered.get(expected_parent_number)
                if expected_parent is not None and section.parent_section_id != expected_parent.section_id:
                    result.numbered_section_parent_mismatch_ids.append(section.element_id)
            latest_numbered[number] = section
        elif section.parent_section_id is None:
            # Major unnumbered boundaries (PART/APPENDIX/etc.) reset the local
            # numbering namespace so repeated numbering in appendices does not
            # compare against the main body.
            latest_numbered = {}

    # A numbered clause belongs to the longest matching numbered section that
    # precedes it.  For example 8.4.2 must not remain under section 8.3 when an
    # 8.4 section exists.
    sections_by_order = sorted(
        sections,
        key=lambda section: element_by_id.get(section.element_id).document_order
        if element_by_id.get(section.element_id) is not None else 10**9,
    )
    major_boundary_re = re.compile(r"^\s*(?:PART|CHAPTER|BOOK|DIVISION|APPENDIX)\b", re.IGNORECASE)
    major_boundaries: list[int] = []
    for section in sections_by_order:
        section_element = element_by_id.get(section.element_id)
        if section_element is None:
            continue
        if section.parent_section_id is None and major_boundary_re.match(section.title or ""):
            major_boundaries.append(section_element.document_order)

    for element in elements:
        if element.type != "clause" or not element.clause_number:
            continue
        clause_match = _NUMBERED_CLAUSE_RE.match(element.clause_number)
        clause_number = clause_match.group(1) if clause_match else element.clause_number
        region_start = max((order for order in major_boundaries if order < element.document_order), default=-1)
        candidates: list[tuple[int, SectionRecord]] = []
        for section in sections_by_order:
            section_element = element_by_id.get(section.element_id)
            if section_element is None:
                continue
            if section_element.document_order <= region_start:
                continue
            if section_element.document_order >= element.document_order:
                break
            number = section_number(section)
            if number and (clause_number == number or clause_number.startswith(number + ".")):
                candidates.append((len(number.split(".")), section))
        if candidates:
            expected = max(candidates, key=lambda item: item[0])[1]
            if not section_is_same_or_descendant(element.section_id, expected.section_id):
                result.clause_section_mismatch_ids.append(element.element_id)

    # Local guidance/note callouts may introduce their own prose/list members,
    # but a fresh numbered clause is a hard scope boundary and must not be
    # swallowed by the callout.
    for relation in relationships:
        if relation.type != "introduces":
            continue
        source = element_by_id.get(relation.source_element_id)
        target = element_by_id.get(relation.target_element_id)
        if (
            source is not None
            and target is not None
            and source.type == "group_header"
            and is_callout_heading(source.text)
            and source.element_id not in appendix_title_sources
            and target.type == "clause"
            and target.clause_number
        ):
            result.callout_scope_leak_relation_ids.append(relation.relation_id)

    children_by_parent: dict[str, list[SectionRecord]] = {}
    for section in sections:
        if section.parent_section_id:
            children_by_parent.setdefault(section.parent_section_id, []).append(section)
    for section in sections:
        if section.kind != "section":
            continue
        if section.content_element_ids:
            continue
        if children_by_parent.get(section.section_id):
            continue
        result.empty_section_scope_ids.append(section.element_id)

    for relation in relationships:
        if relation.type != "continues":
            continue
        source = element_by_id.get(relation.source_element_id)
        target = element_by_id.get(relation.target_element_id)
        if target is not None and target.type == "clause" and target.clause_number:
            result.suspicious_continuation_relation_ids.append(relation.relation_id)
            continue
        if source is None or target is None:
            continue
        target_text = " ".join((target.text or "").split()).strip()
        if (
            ends_complete_sentence(source.text)
            and target_text[:1].isupper()
            and target.type in {"paragraph", "clause", "subclause", "list_item"}
        ):
            result.suspicious_continuation_relation_ids.append(relation.relation_id)

    if result.low_confidence_element_ids:
        result.warnings.append(
            f"Semantic classification review recommended for {len(result.low_confidence_element_ids)} low-confidence element(s) "
            f"(< {low_confidence_threshold:.2f})."
        )
    if result.orphan_group_header_ids:
        result.warnings.append(
            f"Semantic classification review recommended for {len(result.orphan_group_header_ids)} local group header(s) "
            "without an introduces relationship."
        )
    if result.orphan_list_item_ids:
        result.warnings.append(
            f"Semantic hierarchy review recommended for {len(result.orphan_list_item_ids)} enumerated list item(s) "
            "without an introduces/parent relationship."
        )
    if result.empty_section_scope_ids:
        result.warnings.append(
            f"Semantic heading-scope review recommended for {len(result.empty_section_scope_ids)} section heading(s) "
            "that own no direct content and have no child sections."
        )
    if result.suspicious_continuation_relation_ids:
        result.warnings.append(
            f"Semantic continuation review required for {len(result.suspicious_continuation_relation_ids)} relation(s) "
            "whose target begins a fresh numbered clause."
        )
    if result.detached_clause_tail_ids:
        result.warnings.append(
            f"Semantic hierarchy review recommended for {len(result.detached_clause_tail_ids)} paragraph tail(s) "
            "that resume after a list/subclause run without a belongs_to relationship."
        )
    if result.style_split_continuation_ids:
        result.warnings.append(
            f"Semantic continuity review recommended for {len(result.style_split_continuation_ids)} heading/paragraph pair(s) "
            "that still share one Stage 3 block and may be style-only splits."
        )
    if result.redundant_appendix_title_section_ids:
        result.warnings.append(
            f"Semantic heading-scope review recommended for {len(result.redundant_appendix_title_section_ids)} appendix title(s) "
            "that are already represented by AppendixRecord metadata but still create duplicate SectionRecords."
        )
    if result.numbered_section_parent_mismatch_ids:
        result.warnings.append(
            f"Semantic numbering review required for {len(result.numbered_section_parent_mismatch_ids)} numbered section(s) "
            "whose parent conflicts with the explicit outline-number prefix."
        )
    if result.clause_section_mismatch_ids:
        result.warnings.append(
            f"Semantic section ownership review required for {len(result.clause_section_mismatch_ids)} numbered clause(s) "
            "assigned outside the longest matching numbered section."
        )
    if result.callout_scope_leak_relation_ids:
        result.warnings.append(
            f"Semantic callout-scope review required for {len(result.callout_scope_leak_relation_ids)} relation(s) "
            "where a guidance/note callout introduces a fresh numbered clause."
        )
    return result
