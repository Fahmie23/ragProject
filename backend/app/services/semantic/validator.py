from __future__ import annotations

from dataclasses import dataclass, field
import re

from app.schemas import CanonicalElement, SectionRecord, StructuralRelation


_ENUMERATED_PREFIX_RE = re.compile(r"^\s*(?:\([A-Za-z0-9ivxlcdmIVXLCDM]+\)|[A-Za-z0-9]+[.)])\s*")
_APPENDIX_LABEL_RE = re.compile(r"^\s*APPENDIX\s+[A-Z0-9IVXLC]+\s*$", re.IGNORECASE)


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
        target = element_by_id.get(relation.target_element_id)
        if target is not None and target.type == "clause" and target.clause_number:
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
    return result
