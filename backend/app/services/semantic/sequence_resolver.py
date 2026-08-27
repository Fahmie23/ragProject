from __future__ import annotations

import re

from app.schemas import CanonicalElement, StructuredPage
from app.services.semantic.classifier import apply_classification, backfill_classification
from app.services.semantic.features import ElementFeatures, build_feature_map, strip_clause_prefix, strip_marker


_ROMAN_RE = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)
_QUESTION_RE = re.compile(r"\?\s*$")


def _ordered(elements: list[CanonicalElement]) -> list[CanonicalElement]:
    return sorted(elements, key=lambda item: item.document_order)


def _marker_family(tokens: list[str]) -> str:
    # Multi-character Roman markers are unambiguous. Single-character runs such
    # as (a), (b), (c) are alphabetic even if one member happens to be (i).
    if any(len(token) > 1 and _ROMAN_RE.fullmatch(token) for token in tokens):
        return "roman"
    return "alpha"


def _find_previous_meaningful(
    ordered: list[CanonicalElement],
    index: int,
    *,
    skip_types: set[str] | None = None,
    max_back: int = 4,
) -> CanonicalElement | None:
    skipped = skip_types or {"page_header", "page_footer", "footnote", "caption"}
    seen = 0
    for candidate in reversed(ordered[:index]):
        if candidate.type in skipped or not candidate.text.strip():
            continue
        seen += 1
        if seen > max_back:
            break
        return candidate
    return None


def _find_list_introducer(
    ordered: list[CanonicalElement],
    features: dict[str, ElementFeatures],
    first_index: int,
) -> CanonicalElement | None:
    # Look through one short local heading because documents often use:
    #   "... the following types:" -> "Legal persons" -> (a), (b), ...
    meaningful: list[CanonicalElement] = []
    for candidate in reversed(ordered[:first_index]):
        if candidate.type in {"page_header", "page_footer", "footnote", "caption"} or not candidate.text.strip():
            continue
        meaningful.append(candidate)
        if len(meaningful) >= 3:
            break
    for candidate in meaningful:
        feature = features[candidate.element_id]
        if feature.looks_list_intro:
            return candidate
        if not feature.looks_short_label:
            break
    return None


def _candidate_group_header(
    element: CanonicalElement,
    feature: ElementFeatures,
    *,
    list_introducer: CanonicalElement | None,
    next_run_size: int,
) -> bool:
    if element.type not in {"section_header", "paragraph"}:
        return False
    if not feature.looks_short_label or next_run_size < 1:
        return False
    if feature.clause_number is not None:
        return False
    # Local scope is strong when a preceding clause/paragraph explicitly
    # introduces a list. A vendor section-header in that position is usually a
    # group label rather than a document-section boundary.
    return list_introducer is not None


def _promote_numbered_clauses(
    ordered: list[CanonicalElement],
    features: dict[str, ElementFeatures],
) -> None:
    for element in ordered:
        feature = features[element.element_id]
        if element.type not in {"paragraph", "list_item"}:
            continue
        if not feature.clause_number or _QUESTION_RE.search(feature.normalized_text):
            continue
        remainder = strip_clause_prefix(feature.normalized_text)
        if len(remainder) < 12:
            continue
        element.clause_number = feature.clause_number
        element.subclause_marker = None
        element.role_source = "semantic_numbered_clause"
        apply_classification(
            element,
            "clause",
            confidence=0.96,
            source="candidate_classifier",
            evidence=[
                f"numbered prose marker '{feature.clause_number}'",
                "substantive text follows the numbering marker",
                "element is not question-shaped",
            ],
            alternatives=[("list_item", 0.22), ("paragraph", 0.12)],
        )


def _enumerated_runs(
    ordered: list[CanonicalElement],
    features: dict[str, ElementFeatures],
) -> list[list[int]]:
    eligible = {"paragraph", "list_item", "subclause"}
    runs: list[list[int]] = []
    current: list[int] = []
    last_order: int | None = None
    for index, element in enumerate(ordered):
        feature = features[element.element_id]
        if element.type in eligible and feature.marker:
            # A small vertical/header decoration does not count as a semantic
            # run member; runs are deliberately strict so unrelated numbered
            # items are not merged across prose boundaries.
            if current and last_order is not None and element.document_order != last_order + 1:
                runs.append(current)
                current = []
            current.append(index)
            last_order = element.document_order
        else:
            if current:
                runs.append(current)
                current = []
            last_order = None
    if current:
        runs.append(current)
    return runs


def _resolve_enumerated_run(
    ordered: list[CanonicalElement],
    features: dict[str, ElementFeatures],
    run: list[int],
) -> None:
    if not run:
        return
    tokens = [features[ordered[index].element_id].marker_token or "" for index in run]
    family = _marker_family(tokens)
    introducer = _find_list_introducer(ordered, features, run[0])

    # An immediate short heading between the introducer and the run is a local
    # grouping label. This is the key distinction that the previous Stage 4
    # could not represent and therefore over-promoted to section_header.
    immediate_prev = _find_previous_meaningful(ordered, run[0], max_back=1)
    if immediate_prev is not None:
        prev_feature = features[immediate_prev.element_id]
        if _candidate_group_header(
            immediate_prev,
            prev_feature,
            list_introducer=introducer,
            next_run_size=len(run),
        ):
            immediate_prev.heading_level = None
            immediate_prev.heading_level_source = None
            immediate_prev.role_source = "semantic_local_group_header"
            apply_classification(
                immediate_prev,
                "group_header",
                confidence=0.95,
                source="sequence_resolver",
                evidence=[
                    "short unnumbered label immediately precedes an enumerated sequence",
                    "nearby parent text explicitly introduces a list",
                    "local label is scoped to the following items rather than the document outline",
                ],
                alternatives=[("section_header", 0.36), ("paragraph", 0.18)],
            )

    for index in run:
        element = ordered[index]
        feature = features[element.element_id]
        content = strip_marker(feature.normalized_text)
        word_count = len(content.split())

        list_score = 0.0
        subclause_score = 0.0
        evidence_list: list[str] = []
        evidence_sub: list[str] = []

        if feature.layout_role == "list-item":
            list_score += 0.22
            evidence_list.append("layout engine identified a list-item region")
        if len(run) >= 2:
            list_score += 0.18
            subclause_score += 0.08
            evidence_list.append(f"parallel {family} marker sequence contains {len(run)} siblings")
        if introducer is not None:
            list_score += 0.18
            evidence_list.append("nearby parent text introduces an enumeration")
        if feature.ends_semicolon or feature.ends_comma:
            list_score += 0.10
            evidence_list.append("item terminates like a list member")
        if word_count <= 12 and not feature.looks_sentence:
            list_score += 0.10
            evidence_list.append("short item text")
        if not feature.has_modal_or_finite and not feature.looks_sentence:
            list_score += 0.22
            evidence_list.append("text is phrase-like rather than an independent proposition")

        if feature.has_modal_or_finite:
            subclause_score += 0.50
            evidence_sub.append("text contains a finite/modal predicate")
        if feature.looks_sentence:
            subclause_score += 0.30
            evidence_sub.append("text is sentence-shaped")
        if word_count >= 14:
            subclause_score += 0.12
            evidence_sub.append("substantive prose length")
        if feature.ends_period:
            subclause_score += 0.07
        # A subclause is more plausible when the immediately preceding
        # substantive element is already a clause, but this does not override a
        # strong list-introduction context.
        previous = _find_previous_meaningful(ordered, index, max_back=1)
        if previous is not None and previous.type == "clause":
            subclause_score += 0.12
            evidence_sub.append("directly follows a canonical clause")

        # Normalize into [0, 1] scores for auditability.
        total = max(list_score + subclause_score, 0.001)
        list_conf = min(0.99, max(0.01, list_score / total))
        sub_conf = min(0.99, max(0.01, subclause_score / total))

        if list_score >= subclause_score + 0.08:
            element.subclause_marker = None
            element.clause_id = None
            element.parent_clause_id = None
            element.role_source = "semantic_list_sequence"
            apply_classification(
                element,
                "list_item",
                confidence=max(0.70, list_conf),
                source="sequence_resolver",
                evidence=evidence_list,
                alternatives=[("subclause", sub_conf)],
            )
        else:
            element.subclause_marker = feature.marker
            element.role_source = "semantic_subclause_sequence"
            apply_classification(
                element,
                "subclause",
                confidence=max(0.68, sub_conf),
                source="sequence_resolver",
                evidence=evidence_sub or ["enumerated item is more proposition-like than list-like"],
                alternatives=[("list_item", list_conf)],
            )


def _resolve_standalone_markers(
    ordered: list[CanonicalElement],
    features: dict[str, ElementFeatures],
    covered_indexes: set[int],
) -> None:
    for index, element in enumerate(ordered):
        if index in covered_indexes:
            continue
        feature = features[element.element_id]
        if element.type not in {"paragraph", "list_item", "subclause"} or not feature.marker:
            continue
        content = strip_marker(feature.normalized_text)
        if feature.has_modal_or_finite or feature.looks_sentence:
            element.subclause_marker = feature.marker
            element.role_source = "semantic_subclause_single"
            apply_classification(
                element,
                "subclause",
                confidence=0.76,
                source="candidate_classifier",
                evidence=[
                    f"enumerated marker '{feature.marker}'",
                    "content is proposition/sentence-shaped",
                ],
                alternatives=[("list_item", 0.45)],
            )
        else:
            element.subclause_marker = None
            element.role_source = "semantic_list_single"
            apply_classification(
                element,
                "list_item",
                confidence=0.69,
                source="candidate_classifier",
                evidence=[
                    f"enumerated marker '{feature.marker}'",
                    "content is phrase-like and lacks an independent finite/modal predicate",
                ],
                alternatives=[("subclause", 0.48)],
            )


def _resolve_secondary_group_headers(
    ordered: list[CanonicalElement],
    features: dict[str, ElementFeatures],
) -> None:
    """Demote local vendor headings before numbered clauses when evidence is strong.

    This catches structures such as ``Steps ...`` -> ``Legal person`` -> ``1.7``
    without using document-specific vocabulary. We require an earlier real
    section header, a short unnumbered heading, and a following numbered clause.
    Relative typography/indentation provides an additional guard when present.
    """
    for index, element in enumerate(ordered[:-1]):
        if element.type != "section_header":
            continue
        feature = features[element.element_id]
        if not feature.looks_short_label or feature.clause_number is not None:
            continue
        nxt = ordered[index + 1]
        nxt_feature = features[nxt.element_id]
        if nxt.type != "clause" and not nxt_feature.clause_number:
            continue
        previous_header = None
        for prior in reversed(ordered[:index]):
            if prior.type == "section_header":
                previous_header = prior
                break
            if prior.type in {"clause", "table", "figure"}:
                break
        if previous_header is None:
            continue
        if previous_header.text.strip().casefold().startswith("appendix"):
            continue
        prev_feature = features[previous_header.element_id]
        smaller_font = bool(
            feature.dominant_font_size
            and prev_feature.dominant_font_size
            and feature.dominant_font_size <= prev_feature.dominant_font_size
        )
        more_indented = feature.x0 >= prev_feature.x0 + 6.0
        if not (smaller_font or more_indented):
            continue
        element.heading_level = None
        element.heading_level_source = None
        element.role_source = "semantic_local_group_header"
        apply_classification(
            element,
            "group_header",
            confidence=0.84,
            source="sequence_resolver",
            evidence=[
                "short unnumbered vendor heading immediately precedes a numbered clause",
                "a broader section header is already active",
                "typography or indentation indicates narrower local scope",
            ],
            alternatives=[("section_header", 0.55)],
        )


def resolve_structural_semantics(
    elements: list[CanonicalElement],
    pages: list[StructuredPage],
) -> None:
    """Resolve ambiguous structural roles using document context.

    The resolver deliberately does not handle definitions, figures, tables or
    footnotes; their mature specialized passes remain in ``canonical.py``. It
    replaces the old isolated ``(a) => subclause`` promotion with a contextual
    sequence decision and introduces the local ``group_header`` role.
    """
    ordered = _ordered(elements)
    features = build_feature_map(ordered, pages)

    _promote_numbered_clauses(ordered, features)
    # Refresh because numbered-clause type changes influence neighboring runs,
    # while text/geometry features remain stable.
    features = build_feature_map(ordered, pages)

    runs = _enumerated_runs(ordered, features)
    covered: set[int] = set()
    for run in runs:
        _resolve_enumerated_run(ordered, features, run)
        covered.update(run)

    _resolve_standalone_markers(ordered, features, covered)
    _resolve_secondary_group_headers(ordered, features)

    for element in ordered:
        backfill_classification(element)
