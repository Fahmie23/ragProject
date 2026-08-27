from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas import CanonicalElement, SectionRecord, StructuralRelation


@dataclass
class SemanticValidationResult:
    warnings: list[str] = field(default_factory=list)
    low_confidence_element_ids: list[str] = field(default_factory=list)
    orphan_group_header_ids: list[str] = field(default_factory=list)


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
    incoming = {relation.target_element_id for relation in semantic_edges}
    outgoing = {relation.source_element_id for relation in semantic_edges}
    for element in elements:
        if element.type == "group_header" and element.element_id not in incoming and element.element_id not in outgoing:
            result.orphan_group_header_ids.append(element.element_id)

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
    return result
