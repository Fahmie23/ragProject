from __future__ import annotations

from dataclasses import dataclass, field
import re

from app.schemas import CanonicalElement, SectionRecord, StructuralRelation


_ENUMERATED_PREFIX_RE = re.compile(r"^\s*(?:\([A-Za-z0-9ivxlcdmIVXLCDM]+\)|[A-Za-z0-9]+[.)])\s*")


@dataclass
class SemanticValidationResult:
    warnings: list[str] = field(default_factory=list)
    low_confidence_element_ids: list[str] = field(default_factory=list)
    orphan_group_header_ids: list[str] = field(default_factory=list)
    orphan_list_item_ids: list[str] = field(default_factory=list)
    empty_section_scope_ids: list[str] = field(default_factory=list)
    suspicious_continuation_relation_ids: list[str] = field(default_factory=list)


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

    for element in elements:
        if element.type == "group_header" and element.element_id not in incoming_introduces and element.element_id not in outgoing_introduces:
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
    return result
