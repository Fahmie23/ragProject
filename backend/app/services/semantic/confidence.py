from __future__ import annotations

import re

from app.schemas import CanonicalElement, SectionRecord, StructuralRelation
from app.services.semantic.classifier import apply_classification


_APPENDIX_LABEL_RE = re.compile(r"^\s*APPENDIX\s+[A-Z0-9IVXLC]+\s*$", re.IGNORECASE)


def _lower_confidence(
    element: CanonicalElement,
    *,
    ceiling: float,
    evidence: str,
) -> None:
    classification = element.classification
    if classification is None or classification.confidence <= ceiling:
        return
    alternatives = [(item.type, item.score) for item in classification.alternatives]
    apply_classification(
        element,
        classification.selected_type,
        confidence=ceiling,
        source=classification.source,
        evidence=[*classification.evidence, evidence],
        alternatives=alternatives,
        mutate_type=False,
    )


def calibrate_hierarchy_confidence(
    *,
    elements: list[CanonicalElement],
    sections: list[SectionRecord],
    relationships: list[StructuralRelation],
) -> None:
    """Lower semantic confidence when the resolved hierarchy contradicts certainty.

    Classification confidence should describe the *final structural decision*,
    not only text shape.  We therefore keep strong scores when hierarchy agrees
    and conservatively lower them when a dependent item/group/section cannot be
    given coherent ownership.  No semantic type is changed here.
    """
    incoming_introduces = {
        relation.target_element_id
        for relation in relationships
        if relation.type == "introduces"
    }
    incoming_parent = {
        relation.target_element_id
        for relation in relationships
        if relation.type == "parent_of"
    }
    outgoing_introduces = {
        relation.source_element_id
        for relation in relationships
        if relation.type == "introduces"
    }
    element_by_id = {element.element_id: element for element in elements}
    appendix_title_sources: set[str] = set()
    for relation in relationships:
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
        if element.type == "list_item" and element.role_source == "semantic_list_sequence":
            if element.element_id not in incoming_introduces and element.element_id not in incoming_parent:
                _lower_confidence(
                    element,
                    ceiling=0.62,
                    evidence="hierarchy calibration: no introduces/parent relationship was resolved for this dependent list item",
                )
        elif element.type == "group_header":
            if (
                element.element_id not in incoming_introduces
                and element.element_id not in outgoing_introduces
                and element.element_id not in appendix_title_sources
            ):
                _lower_confidence(
                    element,
                    ceiling=0.60,
                    evidence="hierarchy calibration: local group header has no resolved semantic dependency",
                )

    child_sections: set[str] = {
        section.parent_section_id
        for section in sections
        if section.parent_section_id is not None
    }
    for section in sections:
        if section.kind != "section" or section.content_element_ids or section.section_id in child_sections:
            continue
        element = element_by_id.get(section.element_id)
        if element is not None:
            _lower_confidence(
                element,
                ceiling=0.60,
                evidence="hierarchy calibration: section owns no direct content and has no child sections",
            )
