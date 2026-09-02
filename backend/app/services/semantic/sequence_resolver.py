from __future__ import annotations

import re

from app.schemas import CanonicalElement, StructuredPage
from app.services.semantic.classifier import apply_classification, backfill_classification
from app.services.semantic.features import ElementFeatures, build_feature_map, strip_clause_prefix, strip_marker
from app.services.semantic.patterns import is_callout_heading


_ROMAN_RE = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)
_QUESTION_RE = re.compile(r"\?\s*$")
_OBLIGATION_INTRO_RE = re.compile(
    r"\b(?:shall|must|should|(?:is\s+)?required\s+to)(?:\s+[A-Za-z-]+){0,5}\s*(?:[:–—―]|$)",
    re.IGNORECASE,
)
_STRONG_MODAL_RE = re.compile(r"\b(?:shall|must|should|(?:is\s+)?required\s+to)\b", re.IGNORECASE)
_DESCRIPTIVE_INFORMATION_TAIL_RE = re.compile(
    r"\b(?:the\s+)?following\s+(?:information|details?|particulars?|data|documents?|records?)\s*[:–—―]\s*$",
    re.IGNORECASE,
)
_DEONTIC_ENUMERATION_TAIL_RE = re.compile(
    r"\b(?:determine|include|incorporate|undertake|implement|perform|apply|ensure|take)\b"
    r"(?:(?![.!?]).){0,140}\b(?:the\s+following|as\s+follows)\b"
    r"(?:\s+[A-Za-z-]+){0,2}\s*[:–—―]\s*$",
    re.IGNORECASE,
)


def _ordered(elements: list[CanonicalElement]) -> list[CanonicalElement]:
    return sorted(elements, key=lambda item: item.document_order)


def _marker_family(tokens: list[str]) -> str:
    # Multi-character Roman markers are unambiguous. Single-character runs such
    # as (a), (b), (c) are alphabetic even if one member happens to be (i).
    if any(len(token) > 1 and _ROMAN_RE.fullmatch(token) for token in tokens):
        return "roman"
    return "alpha"


def _is_phrase_like_enumerated_label(feature: ElementFeatures) -> bool:
    """Return True for marker-bearing local labels such as ``(a) Phase 1``.

    The label is not itself a legal/propositional subclause; it names a local
    group whose deeper indented enumeration carries the substantive content.
    """
    if not feature.marker:
        return False
    content = strip_marker(feature.normalized_text)
    return bool(
        content
        and len(content.split()) <= 8
        and not feature.has_modal_or_finite
        and not feature.looks_sentence
        and not content.endswith((".", ";", ",", "?"))
    )


def _obligation_list_introducer(element: CanonicalElement | None, features: dict[str, ElementFeatures]) -> bool:
    if element is None:
        return False
    feature = features[element.element_id]
    text = feature.normalized_text
    if not feature.looks_list_intro:
        return False

    # Field/value inventories remain descriptive even when the parent sentence
    # contains a legal obligation (for example, ``required to identify ... by
    # obtaining the following information:``).  Treating those noun-phrase
    # fields as legal subclauses pollutes the clause registry and makes retrieval
    # metadata misleading.
    if _DESCRIPTIVE_INFORMATION_TAIL_RE.search(text):
        return False

    # The modal should belong to the enumeration-introducing sentence rather
    # than to an earlier completed sentence.  This preserves descriptive tails
    # such as ``... should be recorded. Such a situation may be observed
    # through:``.
    tail = re.split(r"(?<=[.!?])\s+", text)[-1]
    if _OBLIGATION_INTRO_RE.search(tail) is not None:
        return True

    # Longer regulatory constructions often place several complements between
    # the modal and the final enumerator, e.g. ``must conduct ... to determine
    # the following:``.  Recognise those by combining a strong modal in the same
    # sentence with an action-oriented enumeration tail instead of increasing a
    # brittle fixed word-count window.
    return bool(_STRONG_MODAL_RE.search(tail) and _DEONTIC_ENUMERATION_TAIL_RE.search(tail))


def _find_previous_parallel_marker(
    ordered: list[CanonicalElement],
    features: dict[str, ElementFeatures],
    first_index: int,
    *,
    max_scan: int = 18,
) -> CanonicalElement | None:
    """Find the previous same-level marker across an intervening nested list.

    This restores an outer sequence after a deeper run, e.g. ``(c) -> (i)..(v)
    -> (d)``.  Geometry, section continuity and marker family all have to agree.
    """
    current = features[ordered[first_index].element_id]
    current_token = current.marker_token or ""
    if not current.marker:
        return None
    seen = 0
    for index in range(first_index - 1, -1, -1):
        candidate = ordered[index]
        if not candidate.text.strip() or candidate.type in {"page_header", "page_footer", "footnote", "caption"}:
            continue
        seen += 1
        if seen > max_scan:
            break
        if candidate.type in {"section_header", "clause", "table", "figure", "definition_term"}:
            break
        feature = features[candidate.element_id]
        if not feature.marker:
            continue
        if abs(feature.x0 - current.x0) > 18.0:
            # A deeper nested marker is intentionally skipped.
            continue
        candidate_token = feature.marker_token or ""
        if _marker_family([candidate_token, current_token]) != _marker_family([current_token]):
            continue
        if candidate.type in {"list_item", "subclause"}:
            return candidate
    return None


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
    """Find the nearest semantic owner that introduces an enumeration.

    Nested enumerated members are transparent during the look-back so an outer
    sequence can resume after an inner list.  Short marker-bearing group labels
    (for example ``(b) Phase 2``) are also transparent.
    """
    seen = 0
    for candidate in reversed(ordered[:first_index]):
        if candidate.type in {"page_header", "page_footer", "footnote", "caption"} or not candidate.text.strip():
            continue
        seen += 1
        if seen > 18:
            break
        feature = features[candidate.element_id]
        if feature.looks_list_intro:
            return candidate
        if feature.marker and candidate.type in {"list_item", "subclause", "paragraph", "group_header"}:
            # Skip members of a nested/parallel list while searching for the
            # parent clause/paragraph that introduced the family.
            continue
        if _is_phrase_like_enumerated_label(feature):
            continue
        if candidate.type == "group_header" or feature.looks_short_label or is_callout_heading(candidate.text):
            continue
        # A substantive boundary that does not introduce a list ends the search.
        if candidate.type in {"section_header", "clause", "paragraph", "table", "figure", "definition_term"}:
            break
    return None


def _find_parallel_group_context(
    ordered: list[CanonicalElement],
    features: dict[str, ElementFeatures],
    heading_index: int,
) -> tuple[CanonicalElement | None, CanonicalElement | None]:
    """Find a preceding local group and its shared list introducer.

    A later group may contain only one enumerated member, so the normal
    ``_find_list_introducer`` look-back can stop on the preceding list items
    before it reaches the original introductory clause.  When a structurally
    parallel ``group_header`` is immediately upstream, reuse its introducer
    only if geometry/typography remain compatible and no stronger boundary is
    crossed.  This keeps the rule document-agnostic.
    """
    candidate = ordered[heading_index]
    candidate_feature = features[candidate.element_id]

    previous_group: CanonicalElement | None = None
    group_index: int | None = None
    for index in range(heading_index - 1, -1, -1):
        item = ordered[index]
        if not item.text.strip() or item.type in {"page_header", "page_footer", "footnote", "caption"}:
            continue
        if item.type in {"list_item", "subclause"}:
            continue
        if item.type == "group_header":
            previous_group = item
            group_index = index
        break

    if previous_group is None or group_index is None:
        return None, None

    previous_feature = features[previous_group.element_id]
    x_tolerance = max(24.0, candidate_feature.page_width * 0.05)
    if abs(candidate_feature.x0 - previous_feature.x0) > x_tolerance:
        return None, None
    if candidate_feature.dominant_font_size and previous_feature.dominant_font_size:
        if abs(candidate_feature.dominant_font_size - previous_feature.dominant_font_size) > 2.0:
            return None, None

    introducer: CanonicalElement | None = None
    for index in range(group_index - 1, -1, -1):
        item = ordered[index]
        if not item.text.strip() or item.type in {"page_header", "page_footer", "footnote", "caption"}:
            continue
        item_feature = features[item.element_id]
        if item_feature.looks_list_intro:
            introducer = item
            break
        # Do not carry local scope across a real outline/content boundary.
        if item.type in {"section_header", "clause", "table", "figure", "definition_term"}:
            break

    return previous_group, introducer


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


def _demote_enumerated_heading_labels(
    ordered: list[CanonicalElement],
    features: dict[str, ElementFeatures],
) -> None:
    """Normalize short marker-bearing headings into list-group labels.

    Some layout engines style ``(a) Phase 1`` as a section header while the
    neighboring ``(b) Phase 2`` is a list item.  When a nearby parent clearly
    introduces an enumeration, normalize the phrase-like heading to list_item so
    the whole marker family can be resolved consistently.
    """
    for index, element in enumerate(ordered):
        if element.type != "section_header":
            continue
        feature = features[element.element_id]
        if not _is_phrase_like_enumerated_label(feature):
            continue
        introducer = _find_list_introducer(ordered, features, index)
        if introducer is None:
            continue
        element.heading_level = None
        element.heading_level_source = None
        element.subclause_marker = None
        element.role_source = "semantic_enumerated_group_label"
        apply_classification(
            element,
            "list_item",
            confidence=0.94,
            source="sequence_resolver",
            evidence=[
                "short marker-bearing heading is phrase-like rather than proposition-shaped",
                "nearby parent text explicitly introduces an enumeration",
                "normalizing vendor heading/list inconsistency preserves one outer marker family",
            ],
            alternatives=[("group_header", 0.04), ("section_header", 0.02)],
        )


def _promote_numbered_clauses(
    ordered: list[CanonicalElement],
    features: dict[str, ElementFeatures],
) -> None:
    for index, element in enumerate(ordered):
        feature = features[element.element_id]
        if element.type not in {"paragraph", "list_item", "section_header"}:
            continue
        # Layout engines sometimes style a clause-level numbered sentence as a
        # heading (for example ``7.3.5 A reporting institution is required to:``).
        # Resolve that narrow case before enumerated-run classification so the
        # following siblings inherit the correct deontic clause context.  Real
        # outline headings are preserved because they normally do not end in a
        # sentence-shaped list introduction.
        if element.type == "section_header" and not (
            feature.clause_number
            and feature.looks_list_intro
            and (feature.has_modal_or_finite or feature.looks_sentence)
        ):
            continue
        previous = _find_previous_meaningful(ordered, index, max_back=1)
        if previous is not None and is_callout_heading(previous.text):
            # Numeric bullets inside a guidance/note box are local guidance
            # members, not global document clauses.
            continue
        if not feature.clause_number or _QUESTION_RE.search(feature.normalized_text):
            continue
        remainder = strip_clause_prefix(feature.normalized_text)
        if len(remainder) < 12 and not feature.looks_list_intro:
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
            # Runs are strict in both document order and indentation.  A nested
            # roman list can be immediately followed by a return to an outer
            # alpha marker (e.g. (i), (ii), then (d)); without the geometry
            # boundary those levels are incorrectly classified as one run.
            if current:
                previous_feature = features[ordered[current[-1]].element_id]
                order_break = last_order is not None and element.document_order != last_order + 1
                indent_break = abs(feature.x0 - previous_feature.x0) > 18.0
                if order_break or indent_break:
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

    # A later parallel group can have only one member.  In that case the
    # immediate look-back is blocked by the preceding group's list members, so
    # recover the shared introducer through the already-resolved group header.
    parallel_group: CanonicalElement | None = None
    immediate_prev_probe = _find_previous_meaningful(ordered, run[0], max_back=1)
    if immediate_prev_probe is not None:
        try:
            heading_index = ordered.index(immediate_prev_probe)
        except ValueError:
            heading_index = -1
        if heading_index >= 0:
            candidate_parallel_group, parallel_introducer = _find_parallel_group_context(ordered, features, heading_index)
            if parallel_introducer is not None and (
                introducer is None or parallel_introducer.element_id == introducer.element_id
            ):
                parallel_group = candidate_parallel_group
                if introducer is None:
                    introducer = parallel_introducer

    run_features = [features[ordered[index].element_id] for index in run]
    x_positions = [feature.x0 for feature in run_features]

    previous_parallel_type: str | None = None
    previous_parallel = _find_previous_parallel_marker(ordered, features, run[0])
    if previous_parallel is not None:
        previous_parallel_type = previous_parallel.type
    parallel_geometry = bool(x_positions) and (max(x_positions) - min(x_positions) <= 18.0)
    nested_list_introducer = introducer is not None and introducer.type != "clause"
    introducer_text = " ".join(introducer.text.split()).strip() if introducer is not None else ""
    obligation_introducer = _obligation_list_introducer(introducer, features)

    # A nested enumerated run may inherit a deontic predicate from the
    # introducer's parent clause.  This is structurally different from a
    # descriptive nested list.  Example:
    #   7.3.5  ... is required to:
    #     (c) take commensurate measures ...:
    #       (i) where higher risks ..., the institution must ensure ...
    # The Roman children are independent conditional obligations and therefore
    # remain subclauses.  By contrast, a descriptive parent such as
    # ``Such a situation can be observed, where:`` continues to own ordinary
    # list items even when those examples happen to contain finite verbs.
    introducer_parent_clause = None
    if introducer is not None and nested_list_introducer:
        try:
            introducer_index = ordered.index(introducer)
        except ValueError:
            introducer_index = -1
        if introducer_index >= 0:
            for candidate in reversed(ordered[:introducer_index]):
                if not candidate.text.strip() or candidate.type in {"page_header", "page_footer", "footnote", "caption"}:
                    continue
                if candidate.type in {"list_item", "subclause", "group_header"}:
                    continue
                if candidate.type == "clause":
                    introducer_parent_clause = candidate
                break
    nested_inherited_obligation = bool(
        nested_list_introducer
        and introducer_parent_clause is not None
        and _obligation_list_introducer(introducer_parent_clause, features)
    )

    # Sequence semantics outrank one member's isolated sentence shape.  A
    # descriptive/list introduction keeps the entire parallel run as list
    # members even when one item contains an incidental finite verb (e.g.
    # "countries identified by ... have not made progress").  Conversely, a
    # parent that ends in an inherited deontic construction such as
    # "is required to–" makes the following verb phrases subclauses even when
    # they omit their own modal verb.
    immediate_prev_for_scope = _find_previous_meaningful(ordered, run[0], max_back=1)
    callout_context = bool(immediate_prev_for_scope is not None and is_callout_heading(immediate_prev_for_scope.text))
    force_subclause_family = bool(
        not callout_context
        and parallel_geometry
        and (
            # When a nested list ends and the parser returns to the same
            # indentation/family as an earlier subclause, that outer sibling
            # sequence outranks a nearer list-introducing sibling.  This
            # restores structures such as ``(c) -> (i)..(v) -> (d) -> (e)``.
            previous_parallel_type == "subclause"
            or (introducer is not None and introducer.type == "clause" and obligation_introducer)
        )
    )
    nested_proposition_member = any(
        (feature.ends_colon or feature.normalized_text.endswith(("–", "—", "―")))
        and (feature.has_modal_or_finite or feature.looks_sentence)
        and len(strip_marker(feature.normalized_text).split()) >= 10
        for feature in run_features
    )
    descriptive_group_context = bool(
        immediate_prev_for_scope is not None
        and immediate_prev_for_scope.type in {"group_header", "list_item"}
        and _is_phrase_like_enumerated_label(features[immediate_prev_for_scope.element_id])
    )
    run_has_strong_modal = any(
        _STRONG_MODAL_RE.search(strip_marker(feature.normalized_text)) is not None
        for feature in run_features
    )
    force_list_family = bool(
        callout_context
        or descriptive_group_context
        or (
            introducer is not None
            and (introducer.type not in {"subclause", "list_item"} or not nested_inherited_obligation)
            and parallel_geometry
            and not obligation_introducer
            and (
                len(run) >= 2
                or (not nested_proposition_member and not run_has_strong_modal)
            )
        )
        # A nested enumerated family under a subclause/list item often consists
        # of dependent measures or categories.  One member may contain an
        # incidental finite/modal predicate (for example a relative ``which
        # should ...`` clause) without becoming a different semantic sibling.
        # When most siblings remain phrase/dependency-shaped, preserve the
        # whole nested run as list items.
        or (
            nested_list_introducer
            and parallel_geometry
            and len(run) >= 2
            and sum(1 for feature in run_features if not feature.has_modal_or_finite and not feature.looks_sentence)
                >= max(1, (len(run) + 1) // 2)
            and previous_parallel_type != "subclause"
        )
        or (introducer is None and parallel_geometry and previous_parallel_type == "list_item")
    )

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
                    *(
                        ["parallel previously-resolved local group shares the same introductory scope"]
                        if parallel_group is not None
                        else []
                    ),
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

        if not force_subclause_family and (force_list_family or list_score >= subclause_score + 0.08):
            if force_list_family:
                if callout_context:
                    evidence_list.append("guidance/note callout scope keeps enumerated members out of the legal clause registry")
                elif descriptive_group_context:
                    evidence_list.append("short outer enumeration label establishes a descriptive nested list group")
                else:
                    evidence_list.append(
                        "cross-page/adjacent parallel sibling family remains a list"
                        if introducer is None and previous_parallel_type == "list_item"
                        else "descriptive list-introduction context and parallel sibling geometry keep the run in one list family"
                    )
                list_conf = max(list_conf, 0.86 if nested_list_introducer else 0.82)
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
            if force_subclause_family:
                evidence_sub.append(
                    "cross-page/adjacent parallel sibling family remains a subclause sequence"
                    if introducer is None and previous_parallel_type == "subclause"
                    else "parent clause supplies an inherited obligation/deontic predicate to the parallel enumerated actions"
                )
                sub_conf = max(sub_conf, 0.86)
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

    _demote_enumerated_heading_labels(ordered, features)
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

    for element in ordered:
        backfill_classification(element)
