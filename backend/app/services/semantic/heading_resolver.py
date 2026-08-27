from __future__ import annotations

from app.schemas import CanonicalElement, StructuredPage
from app.services.semantic.classifier import apply_classification
from app.services.semantic.features import build_feature_map


_STRONG_OUTLINE_SOURCES = {"pdf_toc", "numbering"}
_DECORATION_TYPES = {"page_header", "page_footer", "footnote", "caption", "document_metadata"}


def _ordered(elements: list[CanonicalElement]) -> list[CanonicalElement]:
    return sorted(elements, key=lambda item: item.document_order)


def _next_meaningful(ordered: list[CanonicalElement], start_index: int) -> tuple[int, CanonicalElement] | None:
    for index in range(start_index + 1, len(ordered)):
        item = ordered[index]
        if not item.text.strip() or item.type in _DECORATION_TYPES:
            continue
        return index, item
    return None


def _outline_strength(element: CanonicalElement) -> int:
    source = element.heading_level_source or "unknown"
    if source == "pdf_toc":
        return 3
    if source == "numbering":
        return 2
    if source == "font_rank":
        return 1
    return 0


def resolve_heading_scopes(
    elements: list[CanonicalElement],
    pages: list[StructuredPage],
) -> None:
    """Resolve ambiguous consecutive heading scope conservatively.

    PyMuPDF4LLM and PDF TOC entries are evidence, not absolute semantic truth.
    The safest high-value repair is a *heading stack with no intervening body
    content*: when a weak typography-only heading is immediately followed by a
    stronger TOC/numbering-backed heading, the weak heading is treated as a
    local ``group_header`` rather than an empty sibling section.

    The reverse case is also supported when a strong outline heading is followed
    by a weak short label that immediately scopes a numbered clause.  Ambiguous
    weak/weak or strong/strong pairs are intentionally left unchanged.
    """
    ordered = _ordered(elements)
    features = build_feature_map(ordered, pages)

    for index, element in enumerate(ordered):
        if element.type != "section_header":
            continue
        feature = features[element.element_id]
        if not feature.looks_short_label:
            continue

        nxt_info = _next_meaningful(ordered, index)
        if nxt_info is None:
            continue
        next_index, nxt = nxt_info

        if nxt.type == "section_header":
            current_strength = _outline_strength(element)
            next_strength = _outline_strength(nxt)

            # Weak local label -> strong real outline heading.  This addresses
            # empty sibling sections without overriding TOC/numbering evidence.
            if current_strength <= 1 and next_strength >= 2:
                element.heading_level = None
                element.heading_level_source = None
                element.role_source = "semantic_heading_scope"
                apply_classification(
                    element,
                    "group_header",
                    confidence=0.88,
                    source="heading_scope_resolver",
                    evidence=[
                        "consecutive heading labels have no intervening body content",
                        "following heading has stronger TOC/numbering outline evidence",
                        "current heading level is derived only from typography or is unresolved",
                        "local group scope avoids creating an empty sibling SectionRecord",
                    ],
                    alternatives=[("section_header", 0.12)],
                )
                continue

            # Strong outline heading -> weak short label -> numbered clause.
            # The short label is a local scope marker when the following content
            # clearly starts a clause and geometry does not suggest a broader
            # peer section.  This complements sequence-level list grouping.
            if current_strength >= 2 and next_strength <= 1:
                after_next = _next_meaningful(ordered, next_index)
                if after_next is None:
                    continue
                _, body = after_next
                body_feature = features[body.element_id]
                if body.type != "clause" and not body_feature.clause_number:
                    continue
                next_feature = features[nxt.element_id]
                same_or_deeper_indent = next_feature.x0 >= feature.x0 - 2.0
                if not same_or_deeper_indent:
                    continue
                nxt.heading_level = None
                nxt.heading_level_source = None
                nxt.role_source = "semantic_heading_scope"
                apply_classification(
                    nxt,
                    "group_header",
                    confidence=0.84,
                    source="heading_scope_resolver",
                    evidence=[
                        "short heading is nested immediately below a stronger outline heading",
                        "the next substantive element starts a numbered clause",
                        "local scope is more coherent than another typography-only outline node",
                    ],
                    alternatives=[("section_header", 0.16)],
                )
