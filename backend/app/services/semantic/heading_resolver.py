from __future__ import annotations

import re

from app.schemas import CanonicalElement, StructuredPage
from app.services.semantic.classifier import apply_classification
from app.services.semantic.features import build_feature_map, strip_clause_prefix


_STRONG_OUTLINE_SOURCES = {"pdf_toc", "numbering"}
_DECORATION_TYPES = {"page_header", "page_footer", "footnote", "caption", "document_metadata"}
_APPENDIX_RE = re.compile(r"^\s*APPENDIX\s+[A-Z0-9IVXLC]+\s*$", re.IGNORECASE)
_MAJOR_OUTLINE_RE = re.compile(r"^\s*(?:PART|CHAPTER|BOOK|DIVISION)\s+[A-Z0-9IVXLC]+(?:\s*[:.-]|\s+)", re.IGNORECASE)
_GUIDANCE_RE = re.compile(r"^\s*Guidance\s+for\b", re.IGNORECASE)
_DEFINITION_INTRO_RE = re.compile(r"^\s*(?:means|means[—–-]|refers?\s+to|includes?|in\s+the\s+context\s+of|in\s+relation\s+to)\b", re.IGNORECASE)


def _ordered(elements: list[CanonicalElement]) -> list[CanonicalElement]:
    return sorted(elements, key=lambda item: item.document_order)


def _next_meaningful(ordered: list[CanonicalElement], start_index: int) -> tuple[int, CanonicalElement] | None:
    for index in range(start_index + 1, len(ordered)):
        item = ordered[index]
        if not item.text.strip() or item.type in _DECORATION_TYPES:
            continue
        return index, item
    return None


def _previous_meaningful(ordered: list[CanonicalElement], start_index: int) -> tuple[int, CanonicalElement] | None:
    for index in range(start_index - 1, -1, -1):
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


def _number_parts(number: str | None) -> tuple[str, ...]:
    if not number:
        return ()
    return tuple(part for part in number.strip(". ").split(".") if part)


def _number_depth(number: str | None) -> int:
    return len(_number_parts(number))


def _number_is_child(child: str | None, parent: str | None) -> bool:
    if not child or not parent:
        return False
    child_parts = _number_parts(child)
    parent_parts = _number_parts(parent)
    return len(child_parts) > len(parent_parts) and child_parts[: len(parent_parts)] == parent_parts


def _same_number_family(a: str | None, b: str | None) -> bool:
    a_parts = _number_parts(a)
    b_parts = _number_parts(b)
    return bool(a_parts and b_parts and len(a_parts) == len(b_parts) and a_parts[0] == b_parts[0])


def _next_numbered(ordered: list[CanonicalElement], features, start_index: int, max_scan: int = 12) -> CanonicalElement | None:
    seen = 0
    for index in range(start_index + 1, len(ordered)):
        item = ordered[index]
        if item.type in _DECORATION_TYPES or not item.text.strip():
            continue
        seen += 1
        feature = features[item.element_id]
        if feature.clause_number:
            return item
        if item.type == "section_header" and not feature.looks_short_label:
            return None
        if seen >= max_scan:
            break
    return None


def _previous_numbered(ordered: list[CanonicalElement], features, start_index: int, max_scan: int = 12) -> CanonicalElement | None:
    seen = 0
    for index in range(start_index - 1, -1, -1):
        item = ordered[index]
        if item.type in _DECORATION_TYPES or not item.text.strip():
            continue
        seen += 1
        feature = features[item.element_id]
        if feature.clause_number:
            return item
        if item.type == "section_header" and not feature.looks_short_label:
            return None
        if seen >= max_scan:
            break
    return None


def _promote_numbered_heading_clauses(
    ordered: list[CanonicalElement],
    pages: list[StructuredPage],
) -> None:
    """Convert heading-looking numbered prose back into clauses when hierarchy says so.

    PDF bookmarks frequently contain bold procedural steps (for example ``1.8
    Step 1: ...``), causing the layout engine to call them section headers.  A
    heading label is preserved when it owns a deeper numbered family (``8.1``
    -> ``8.1.1``) or uses the conventional ``x.0`` section form.  Otherwise a
    same-depth sequence surrounded by clauses is semantic clause content.
    """
    features = build_feature_map(ordered, pages)
    for index, element in enumerate(ordered):
        if element.type != "section_header":
            continue
        feature = features[element.element_id]
        number = feature.clause_number
        if not number or _APPENDIX_RE.fullmatch(feature.normalized_text):
            continue

        parts = _number_parts(number)
        if not parts:
            continue
        if parts[-1] == "0":
            continue

        next_numbered = _next_numbered(ordered, features, index)
        if next_numbered is not None:
            next_number = features[next_numbered.element_id].clause_number
            if _number_is_child(next_number, number):
                # This heading owns a deeper numbered family and is therefore a
                # genuine outline section/subsection.
                continue

        previous_numbered = _previous_numbered(ordered, features, index)
        previous_number = features[previous_numbered.element_id].clause_number if previous_numbered else None
        next_number = features[next_numbered.element_id].clause_number if next_numbered else None

        depth = _number_depth(number)
        sequential_context = _same_number_family(number, previous_number) or _same_number_family(number, next_number)
        next_meaningful = _next_meaningful(ordered, index)
        followed_by_dependent_body = bool(
            next_meaningful
            and next_meaningful[1].type in {"list_item", "subclause", "paragraph"}
        )

        # Three-or-more-part numbers are overwhelmingly clause-level content in
        # this canonical taxonomy.  Two-part numbers are promoted only when
        # same-depth numbering/children show they are procedural clauses rather
        # than subsection labels.
        previous_is_clause = previous_numbered is not None and previous_numbered.type == "clause"
        if depth < 3 and not (
            (sequential_context and followed_by_dependent_body)
            or (previous_is_clause and _same_number_family(number, previous_number))
        ):
            continue

        remainder = strip_clause_prefix(feature.normalized_text)
        if len(remainder) < 8:
            continue

        element.clause_number = number
        element.heading_level = None
        element.heading_level_source = None
        element.subclause_marker = None
        element.role_source = "semantic_numbered_heading_clause"
        apply_classification(
            element,
            "clause",
            confidence=0.95,
            source="heading_scope_resolver",
            evidence=[
                f"numbered heading marker '{number}' participates in clause-level sequence",
                "no deeper numbered child family establishes this element as an outline section",
                "numbered content is followed by dependent clause/list body",
                "semantic numbering context overrides heading-like typography",
            ],
            alternatives=[("section_header", 0.05)],
        )


def _demote_to_group(element: CanonicalElement, *, confidence: float, evidence: list[str]) -> None:
    element.heading_level = None
    element.heading_level_source = None
    element.role_source = "semantic_heading_scope"
    apply_classification(
        element,
        "group_header",
        confidence=confidence,
        source="heading_scope_resolver",
        evidence=evidence,
        alternatives=[("section_header", max(0.01, 1.0 - confidence))],
    )


def resolve_heading_scopes(
    elements: list[CanonicalElement],
    pages: list[StructuredPage],
) -> None:
    """Resolve outline sections versus local semantic group headings.

    The resolver intentionally treats PDF TOC/bookmark hierarchy as evidence,
    not authority.  It combines numbering ownership, local group state and
    adjacent clause/list context.  This prevents a local label from polluting
    the SectionRecord stack and incorrectly adopting later real sections.
    """
    ordered = _ordered(elements)

    # First recover clauses that a bookmark/layout engine styled as headings.
    _promote_numbered_heading_clauses(ordered, pages)
    features = build_feature_map(ordered, pages)

    # Existing v2.1 high-confidence consecutive-heading repair.  Run before the
    # stateful scope walk because it seeds useful local-group context.
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
        if nxt.type != "section_header":
            continue

        current_strength = _outline_strength(element)
        next_strength = _outline_strength(nxt)
        if current_strength <= 1 and next_strength >= 2:
            _demote_to_group(
                element,
                confidence=0.88,
                evidence=[
                    "consecutive heading labels have no intervening body content",
                    "following heading has stronger TOC/numbering outline evidence",
                    "current heading level is derived only from typography or is unresolved",
                    "local group scope avoids creating an empty sibling SectionRecord",
                ],
            )
            continue

        if current_strength >= 2 and next_strength <= 1:
            after_next = _next_meaningful(ordered, next_index)
            if after_next is None:
                continue
            _, body = after_next
            body_feature = features[body.element_id]
            if body.type != "clause" and not body_feature.clause_number:
                continue
            next_feature = features[nxt.element_id]
            if next_feature.x0 < feature.x0 - 2.0:
                continue
            _demote_to_group(
                nxt,
                confidence=0.84,
                evidence=[
                    "short heading is nested immediately below a stronger outline heading",
                    "the next substantive element starts a numbered clause",
                    "local scope is more coherent than another typography-only outline node",
                ],
            )

    # Rebuild features after mutations and perform the broader stateful scope
    # walk.  A local group remains active until a genuine section/appendix
    # boundary appears; this lets related labels span intervening body clauses.
    features = build_feature_map(ordered, pages)
    active_group: CanonicalElement | None = None
    active_numbered_outline: CanonicalElement | None = None
    inside_appendix = False

    for index, element in enumerate(ordered):
        text = " ".join(element.text.split()).strip()
        if not text:
            continue

        if _APPENDIX_RE.fullmatch(text):
            active_group = None
            active_numbered_outline = element if element.type == "section_header" else None
            inside_appendix = True
            continue

        if element.type == "section_header" and _MAJOR_OUTLINE_RE.match(text):
            active_group = None
            active_numbered_outline = element
            inside_appendix = False
            continue

        if element.type == "group_header":
            active_group = element
            continue

        if element.type != "section_header":
            continue

        feature = features[element.element_id]
        if feature.clause_number:
            active_group = None
            active_numbered_outline = element
            continue

        prev_info = _previous_meaningful(ordered, index)
        next_info = _next_meaningful(ordered, index)
        previous = prev_info[1] if prev_info else None
        nxt = next_info[1] if next_info else None
        next_feature = features[nxt.element_id] if nxt is not None else None

        # Definition terms can be styled as headings.  If the immediately
        # following body starts a definition-intro phrase, leave the candidate
        # untouched for the specialized definition resolver rather than
        # converting it into a local group header.
        if nxt is not None and _DEFINITION_INTRO_RE.match(" ".join(nxt.text.split()).strip()):
            active_group = None
            continue

        reasons: list[str] = []

        if _GUIDANCE_RE.match(text):
            reasons.append("guidance/callout heading is local to the active substantive section")

        if active_group is not None and (
            inside_appendix
            or active_numbered_outline is not None
            or _outline_strength(element) <= 1
        ):
            reasons.append("an unresolved local group scope is already active in the current outline region")

        if (
            nxt is not None
            and nxt.type == "clause"
            and nxt.clause_number
            and active_numbered_outline is not None
            and features[active_numbered_outline.element_id].clause_number
            and _number_is_child(nxt.clause_number, features[active_numbered_outline.element_id].clause_number)
        ):
            reasons.append(
                f"following clause {nxt.clause_number} remains inside numbered outline "
                f"{features[active_numbered_outline.element_id].clause_number}"
            )

        if previous is not None and previous.type == "clause":
            previous_feature = features[previous.element_id]
            if previous_feature.looks_list_intro and nxt is not None and nxt.type in {
                "paragraph", "list_item", "subclause", "clause"
            }:
                reasons.append("preceding clause explicitly introduces a locally grouped body")

        if reasons:
            _demote_to_group(
                element,
                confidence=0.91 if len(reasons) >= 2 else 0.86,
                evidence=[
                    *reasons,
                    "local group semantics prevent this label from creating a persistent SectionRecord",
                ],
            )
            active_group = element
            continue

        # A surviving unnumbered section is a real scope boundary.  It clears
        # local group state; numbering context will be re-established by a later
        # numbered outline heading if one appears.
        active_group = None
        active_numbered_outline = None
