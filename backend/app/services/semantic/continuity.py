from __future__ import annotations

import re

from app.schemas import CanonicalElement, StructuredPage
from app.services.semantic.classifier import apply_classification
from app.services.semantic.features import build_feature_map, extract_clause_number, extract_marker


_APPENDIX_RE = re.compile(r"^\s*APPENDIX\s+[A-Z0-9IVXLC]+\s*$", re.IGNORECASE)
_CONTINUATION_START_RE = re.compile(
    r"^\s*(?:and|or|but|nor|yet|so|which|that|where|whereby|while|when|who|whose|to|of|with|for|"
    r"including|as|in|on|by|from|under|through|together|among)\b",
    re.IGNORECASE,
)
_TERMINAL_BOUNDARY_RE = re.compile(r"[.!?;:]\s*$")
_MARKER_ONLY_RE = re.compile(r"^\s*(?:\((?:[A-Za-z]|\d{1,3}|[ivxlcdmIVXLCDM]{1,8})\)|(?:\d{1,3}|[A-Za-z])[.)])\s*$")
_DEFINITION_BODY_START_RE = re.compile(
    r"^\s*(?:means?|refers?\s+to|includes?|has\s+the\s+meaning|is\s+defined\s+as)\b",
    re.IGNORECASE,
)


def _ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _shared_stage3_block(left: CanonicalElement, right: CanonicalElement) -> bool:
    return bool(set(left.source.stage3_block_ids) & set(right.source.stage3_block_ids))


def _font_compatible(left: CanonicalElement, right: CanonicalElement, tolerance: float = 1.5) -> bool:
    if left.dominant_font_size is None or right.dominant_font_size is None:
        return True
    return abs(float(left.dominant_font_size) - float(right.dominant_font_size)) <= tolerance


def _vertical_gap(left: CanonicalElement, right: CanonicalElement) -> float:
    return float(right.bbox[1]) - float(left.bbox[3])


def _has_fresh_marker(text: str) -> bool:
    marker, _ = extract_marker(text)
    return marker is not None or extract_clause_number(text) is not None


def _merge_source_trace(left: CanonicalElement, right: CanonicalElement) -> None:
    left.source.stage3_block_ids = _ordered_unique(left.source.stage3_block_ids + right.source.stage3_block_ids)
    left.source.stage3_line_ids = _ordered_unique(left.source.stage3_line_ids + right.source.stage3_line_ids)
    left.source.stage3_span_ids = _ordered_unique(left.source.stage3_span_ids + right.source.stage3_span_ids)
    left.source.stage3_table_ids = _ordered_unique(left.source.stage3_table_ids + right.source.stage3_table_ids)


def _merge_bbox(left: CanonicalElement, right: CanonicalElement) -> None:
    left.bbox = [
        min(float(left.bbox[0]), float(right.bbox[0])),
        min(float(left.bbox[1]), float(right.bbox[1])),
        max(float(left.bbox[2]), float(right.bbox[2])),
        max(float(left.bbox[3]), float(right.bbox[3])),
    ]


def _merge_text(left: CanonicalElement, right: CanonicalElement) -> None:
    left_text = (left.text or "").rstrip()
    right_text = (right.text or "").lstrip()
    if not left_text:
        left.text = right_text
    elif not right_text:
        left.text = left_text
    else:
        # Preserve a visible reconstruction boundary without inventing or
        # rewriting source wording. Stage 5 normalizes whitespace later.
        left.text = f"{left_text}\n{right_text}"


def _merge_into_left(
    left: CanonicalElement,
    right: CanonicalElement,
    *,
    selected_type: str,
    confidence: float,
    evidence: list[str],
) -> None:
    _merge_text(left, right)
    _merge_bbox(left, right)
    _merge_source_trace(left, right)

    if selected_type != "section_header":
        left.heading_level = None
        left.heading_level_source = None
        left.section_id = None
    if selected_type not in {"clause", "subclause"}:
        left.clause_number = None
        left.clause_id = None
        left.parent_clause_id = None
        left.subclause_marker = None

    left.role_source = "semantic_same_unit_continuation"
    apply_classification(
        left,
        selected_type,
        confidence=confidence,
        source="continuity_resolver",
        evidence=evidence,
        alternatives=[],
    )


def _vertical_overlap_ratio(left: CanonicalElement, right: CanonicalElement) -> float:
    overlap = max(0.0, min(float(left.bbox[3]), float(right.bbox[3])) - max(float(left.bbox[1]), float(right.bbox[1])))
    denom = max(1.0, min(float(left.bbox[3]) - float(left.bbox[1]), float(right.bbox[3]) - float(right.bbox[1])))
    return overlap / denom


def _is_marker_only_fragment_pair(left: CanonicalElement, right: CanonicalElement) -> bool:
    """Detect a list marker split from its same-line content by the layout engine."""
    if left.type not in {"list_item", "subclause", "paragraph"}:
        return False
    if right.type not in {"list_item", "paragraph"}:
        return False
    if _MARKER_ONLY_RE.fullmatch(" ".join((left.text or "").split()).strip()) is None:
        return False
    if _has_fresh_marker(right.text):
        return False
    if not _shared_stage3_block(left, right):
        return False
    if _vertical_overlap_ratio(left, right) < 0.65:
        return False
    horizontal_gap = float(right.bbox[0]) - float(left.bbox[2])
    if horizontal_gap < -3.0 or horizontal_gap > 48.0:
        return False
    return _font_compatible(left, right, tolerance=2.0)


def _is_wrapped_heading_fragment(left: CanonicalElement, right: CanonicalElement) -> bool:
    """Merge a single heading that the vendor split across adjacent lines/boxes."""
    if left.type not in {"section_header", "group_header"} or right.type not in {"section_header", "group_header"}:
        return False
    if not _shared_stage3_block(left, right):
        return False
    if _has_fresh_marker(left.text) or _has_fresh_marker(right.text):
        return False
    if not _font_compatible(left, right, tolerance=1.0):
        return False
    gap = _vertical_gap(left, right)
    if gap < -1.0 or gap > 9.0:
        return False
    if abs(float(left.bbox[0]) - float(right.bbox[0])) > 8.0:
        return False
    left_text = " ".join((left.text or "").split()).strip()
    right_text = " ".join((right.text or "").split()).strip()
    if not left_text or not right_text or _TERMINAL_BOUNDARY_RE.search(left_text):
        return False
    # Keep this intentionally narrow: wrapped headings are short label-like
    # fragments, not two full prose sentences that happen to share a raw block.
    return len(left_text.split()) <= 10 and len(right_text.split()) <= 6 and len((left_text + " " + right_text).split()) <= 14


def _is_unmarked_body_continuation(
    left: CanonicalElement,
    right: CanonicalElement,
) -> bool:
    if left.type not in {"clause", "subclause", "list_item", "paragraph"}:
        return False
    if right.type not in {"paragraph", "list_item"}:
        return False
    if _has_fresh_marker(right.text):
        return False
    if not _shared_stage3_block(left, right):
        return False
    gap = _vertical_gap(left, right)
    if gap < -1.0 or gap > 14.0:
        return False
    if not _font_compatible(left, right):
        return False
    # A continuation line may align to the body text after an enumeration
    # marker, so allow a modest rightward shift but reject a column jump.
    if float(right.bbox[0]) < float(left.bbox[0]) - 5.0:
        return False
    if float(right.bbox[0]) > float(left.bbox[0]) + 42.0:
        return False

    left_text = " ".join((left.text or "").split()).strip()
    right_text = " ".join((right.text or "").split()).strip()
    if not left_text or not right_text:
        return False
    # Do not collapse a short definition term into a following definition body.
    # Definition reconstruction needs those roles to remain separately recoverable.
    if _DEFINITION_BODY_START_RE.match(right_text) and len(left_text.split()) <= 10:
        return False
    if _TERMINAL_BOUNDARY_RE.search(left_text):
        return False
    # Lower-case/connective continuation is deliberately conservative. It
    # catches layout splits such as "...take actions" -> "and make decisions"
    # without joining ordinary adjacent paragraphs.
    return bool(right_text[:1].islower() or _CONTINUATION_START_RE.match(right_text))


def _is_style_split_sentence(
    left: CanonicalElement,
    right: CanonicalElement,
    *,
    features,
) -> bool:
    if left.type != "section_header" or right.type != "paragraph":
        return False
    if left.role_source != "layout":
        return False
    if left.heading_level_source not in {"font_rank", "unknown", None}:
        return False
    if _APPENDIX_RE.fullmatch(" ".join((left.text or "").split()).strip()):
        return False
    if _has_fresh_marker(left.text) or _has_fresh_marker(right.text):
        return False
    if not _shared_stage3_block(left, right):
        return False
    gap = _vertical_gap(left, right)
    if gap < -1.0 or gap > 10.0:
        return False
    if abs(float(left.bbox[0]) - float(right.bbox[0])) > 8.0:
        return False
    if not _font_compatible(left, right):
        return False

    left_text = " ".join((left.text or "").split()).strip()
    if not left_text or _TERMINAL_BOUNDARY_RE.search(left_text):
        return False
    left_feature = features.get(left.element_id)
    right_feature = features.get(right.element_id)
    if left_feature is None or right_feature is None:
        return False
    # A short unnumbered label is more likely to be a genuine local heading
    # than the first half of a sentence. Keep it separate even when the raw
    # extraction block is shared.
    if left_feature.looks_short_label:
        return False
    # Preserve definition term/body boundaries for the specialized definition
    # reconstruction pass.
    if _DEFINITION_BODY_START_RE.match(right_feature.normalized_text):
        return False
    # Multi-field forms can share a raw block with a local label and often end
    # every field in a colon. That is layout grouping, not sentence continuity.
    if (right.text or "").count(":") >= 2:
        return False
    # The following box must supply sentence/predicate content, and in the
    # strongest case it introduces the list immediately below. This avoids
    # demoting ordinary appendix/form labels that merely happen to share a raw
    # Stage-3 block.
    return bool(right_feature.looks_list_intro or right_feature.has_modal_or_finite)


def reconcile_same_page_semantic_continuity(
    elements: list[CanonicalElement],
    pages: list[StructuredPage],
) -> list[str]:
    """Merge adjacent layout fragments that are demonstrably one semantic unit.

    The pass is conservative and source-grounded.  It requires adjacent boxes
    to share a Stage-3 block, compatible geometry/typography, and no fresh
    structural marker.  This repairs two generic failure modes:

    * a clause/subclause body split into a markerless continuation box; and
    * a style-only bold fragment misread as a heading even though it continues
      directly into the following paragraph.

    The left element id is retained and all Stage-3 provenance is unioned, so
    downstream corrections and citations still resolve to original evidence.
    """
    removed_ids: list[str] = []

    for page in pages:
        changed = True
        while changed:
            changed = False
            page.elements.sort(key=lambda item: item.reading_order)
            features = build_feature_map(elements, pages)
            for index in range(len(page.elements) - 1):
                left = page.elements[index]
                right = page.elements[index + 1]

                if _is_marker_only_fragment_pair(left, right):
                    selected_type = "list_item" if left.type != "subclause" else "subclause"
                    _merge_into_left(
                        left,
                        right,
                        selected_type=selected_type,
                        confidence=0.98,
                        evidence=[
                            "marker-only fragment and following content share the same Stage 3 text block",
                            "fragments occupy the same visual row with a small horizontal gap",
                            "following fragment has no fresh structural marker",
                            "marker and content reconstructed as one enumerated semantic unit",
                        ],
                    )
                elif _is_wrapped_heading_fragment(left, right):
                    selected_type = "group_header" if "group_header" in {left.type, right.type} else "section_header"
                    _merge_into_left(
                        left,
                        right,
                        selected_type=selected_type,
                        confidence=0.97,
                        evidence=[
                            "adjacent heading fragments share the same Stage 3 text block",
                            "heading fragments align vertically with compatible typography",
                            "neither fragment starts a new numbered/enumerated unit",
                            "wrapped heading reconstructed as one semantic label",
                        ],
                    )
                elif _is_unmarked_body_continuation(left, right):
                    selected_type = left.type
                    _merge_into_left(
                        left,
                        right,
                        selected_type=selected_type,
                        confidence=max(0.92, left.classification.confidence if left.classification else 0.0),
                        evidence=[
                            "adjacent fragments share the same Stage 3 text block",
                            "next fragment has no fresh numbering/list marker",
                            "geometry and font size are compatible",
                            "previous fragment ends mid-thought and the next fragment begins like grammatical continuation",
                            "fragments reconstructed as one semantic unit",
                        ],
                    )
                elif _is_style_split_sentence(left, right, features=features):
                    _merge_into_left(
                        left,
                        right,
                        selected_type="paragraph",
                        confidence=0.94,
                        evidence=[
                            "heading-like and paragraph fragments share the same Stage 3 text block",
                            "typography-only heading evidence is weaker than same-block sentence continuity",
                            "fragments are adjacent and horizontally aligned with compatible font size",
                            "following fragment supplies predicate/list-introduction content",
                            "style change is treated as emphasis rather than a semantic section boundary",
                        ],
                    )
                else:
                    continue

                removed_ids.append(right.element_id)
                page.elements.pop(index + 1)
                try:
                    elements.remove(right)
                except ValueError:
                    pass
                changed = True
                break

    return removed_ids
