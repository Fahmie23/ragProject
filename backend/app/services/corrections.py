from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from math import isfinite
import re

from app.services.canonical import _build_definition_entries, _text_looks_incomplete
from app.services.spans import iter_page_spans, span_map
from app.schemas import (
    CanonicalElement,
    CanonicalSourceTrace,
    ClauseRecord,
    CorrectionArtifact,
    CorrectionElementSpec,
    CorrectionOperation,
    CorrectionRelationshipSpec,
    IntegrityIssue,
    DocumentExtraction,
    RelationshipIntegrityReport,
    RelationshipReviewState,
    ResolvedStructureArtifact,
    SectionRecord,
    StructuralRelation,
    StructuredDocument,
)


CONTENT_TYPES = {
    "title",
    "subtitle",
    "section_header",
    "clause",
    "subclause",
    "definition_term",
    "definition_text",
    "paragraph",
    "list_item",
    "table",
    "caption",
    "footnote",
    "formula",
}

RELATIONSHIP_OPERATIONS = {"add_relationship", "remove_relationship"}
DEFINITION_MEMBERSHIP_OPERATIONS = {"link_definition", "unlink_definition", "assign_definition", "unassign_definition"}
STRUCTURAL_OPERATIONS = {"set_structure"}
MANUAL_RELATION_TYPES = {"continues"}
GEOMETRY_OPERATIONS = {"move_resize", "split", "merge", "draw", "span_rebuild"}
SAFE_SPLIT_MERGE_TYPES = {
    "paragraph",
    "definition_text",
    "list_item",
    "caption",
    "footnote",
    "formula",
}
SAFE_SPLIT_TYPES = SAFE_SPLIT_MERGE_TYPES | {"page_header", "page_footer"}
# These element kinds carry document-level records or metadata that cannot be
# created safely by the generic bbox/type editor alone. They require a
# dedicated structural editor that captures the extra semantic fields.
STRUCTURAL_PROMOTION_TYPES = {
    "title",
    "subtitle",
    "document_metadata",
    "section_header",
    "clause",
    "subclause",
    "table",
    "figure",
}
SAFE_DRAW_TYPES = {
    "definition_term",
    "definition_text",
    "paragraph",
    "list_item",
    "caption",
    "page_header",
    "page_footer",
    "footnote",
    "formula",
    "unknown",
}

# Span reconstruction deliberately targets leaf/content semantics only. Record-
# bearing structures (sections, clauses, tables, figures, document metadata)
# require dedicated editors because selecting text spans alone cannot provide
# their required canonical metadata safely.
SAFE_SPAN_REBUILD_TYPES = set(SAFE_DRAW_TYPES)

RECOVERED_DEFINITION_ROLES = {
    "definition_row_recovery_span_columns",
    "definition_row_recovery_text_pattern",
    "definition_parallel_stream_recovery",
    "definition_table_semantic_normalization",
}

# Warnings in this set are not graph-corruption errors, but they can change how
# downstream chunking interprets hierarchy or cross-page membership. Stage 5
# therefore remains blocked until a reviewer explicitly approves them.
REVIEW_REQUIRED_WARNING_CODES = {
    "subclause_without_parent",
    "section_level_conflict",
    "clause_sibling_order",
    "clause_sibling_gap",
    "subclause_sibling_order",
    "subclause_sibling_gap",
    "table_fragment_section_conflict",
    "continues_type_mismatch",
    "continues_table_partial_membership",
    "continues_definition_partial_membership",
    "continues_page_gap",
    "possible_cross_page_clause_continuation",
    "belongs_to_untyped",
}


class StaleCorrectionError(ValueError):
    pass


class InvalidCorrectionError(ValueError):
    pass


def _normalize_legacy_definition_provenance(structure: StructuredDocument) -> None:
    """Migrate pre-1.6 definition provenance in memory.

    Older Stage-4 artifacts already stored ``source_table_element_id`` but did
    not store ``source_kind``. Pydantic therefore loads them with the modern
    default ``layout_columns``, which makes valid normalized table definitions
    look like broken live table foreign keys. In the current model a non-null
    ``source_table_element_id`` is only produced for table-derived definitions,
    so it can be upgraded safely and non-destructively at resolve time.
    """
    for entry in structure.definitions:
        if entry.source_table_element_id:
            entry.source_kind = "table_rows"


def _intersection_area(a: list[float], b: list[float]) -> float:
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _area(bbox: list[float]) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def _center_inside(inner: list[float], outer: list[float]) -> bool:
    cx = (inner[0] + inner[2]) / 2
    cy = (inner[1] + inner[3]) / 2
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def _normalize_bbox(bbox: list[float], width: float, height: float) -> list[float]:
    if len(bbox) != 4:
        raise InvalidCorrectionError("Bounding boxes must contain exactly four coordinates.")
    try:
        x0, y0, x1, y1 = [float(value) for value in bbox]
    except (TypeError, ValueError) as exc:
        raise InvalidCorrectionError("Bounding-box coordinates must be numeric.") from exc
    if not all(isfinite(value) for value in (x0, y0, x1, y1)):
        raise InvalidCorrectionError("Bounding-box coordinates must be finite numbers.")

    x0, x1 = sorted((max(0.0, min(width, x0)), max(0.0, min(width, x1))))
    y0, y1 = sorted((max(0.0, min(height, y0)), max(0.0, min(height, y1))))
    if x1 - x0 < 1.0 or y1 - y0 < 1.0:
        raise InvalidCorrectionError("Bounding boxes must have a width and height of at least 1 PDF point.")
    return [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)]


def _overlap_fraction_of_smaller(a: list[float], b: list[float]) -> float:
    smaller = max(min(_area(a), _area(b)), 1.0)
    return _intersection_area(a, b) / smaller


def _geometry_matches_region(source_bbox: list[float], region_bbox: list[float], threshold: float = 0.35) -> bool:
    """Return True when source geometry meaningfully belongs to a corrected region.

    Corrections are often intentionally tighter than Stage-3 blocks/spans.  A
    ratio measured only against the large Stage-3 object misses that case.  We
    therefore also consider overlap relative to the smaller geometry and the
    corrected-region centre falling inside the source geometry.
    """
    source_area = max(_area(source_bbox), 1.0)
    overlap_source = _intersection_area(source_bbox, region_bbox) / source_area
    return (
        overlap_source >= threshold
        or _overlap_fraction_of_smaller(source_bbox, region_bbox) >= threshold
        or _center_inside(source_bbox, region_bbox)
        or _center_inside(region_bbox, source_bbox)
    )


def _raw_page(extraction: DocumentExtraction, page_number: int):
    return next((page for page in extraction.pages if page.page_number == page_number), None)


def _union_bboxes(bboxes: list[list[float]]) -> list[float]:
    if not bboxes:
        raise InvalidCorrectionError("At least one bounding box is required.")
    return [
        round(min(box[0] for box in bboxes), 3),
        round(min(box[1] for box in bboxes), 3),
        round(max(box[2] for box in bboxes), 3),
        round(max(box[3] for box in bboxes), 3),
    ]


def _bbox_close(left: list[float], right: list[float], tolerance: float = 1.0) -> bool:
    return len(left) == 4 and len(right) == 4 and all(abs(float(a) - float(b)) <= tolerance for a, b in zip(left, right))


def _span_text_trace_and_bbox(
    extraction: DocumentExtraction,
    page_number: int,
    span_ids: list[str],
    source_class: str,
) -> tuple[str, CanonicalSourceTrace, list[float]]:
    """Resolve exact Stage-3 span IDs into deterministic text, provenance and bbox.

    The caller supplies stable span IDs rather than geometry guesses. Legacy
    Stage-3 schema 1.0 artifacts are supported because ``span_map`` synthesizes
    deterministic IDs from the immutable block/line/span nesting.
    """
    if not span_ids:
        raise InvalidCorrectionError("Span-based correction requires at least one source_span_id.")
    if len(span_ids) != len(set(span_ids)):
        raise InvalidCorrectionError("source_span_ids must be unique within one result element.")

    raw_page = _raw_page(extraction, page_number)
    if raw_page is None:
        raise InvalidCorrectionError(f"Stage 3 page {page_number} was not found for span correction.")
    by_id = span_map(raw_page)
    missing = [span_id for span_id in span_ids if span_id not in by_id]
    if missing:
        raise InvalidCorrectionError(f"Unknown Stage 3 span IDs on page {page_number}: {', '.join(missing)}")

    selected = [by_id[span_id] for span_id in span_ids]
    selected.sort(key=lambda item: (item.block_index, item.line_index, item.span_index))

    lines: list[str] = []
    current_key: tuple[int, int] | None = None
    current_parts: list[str] = []
    for item in selected:
        key = (item.block_index, item.line_index)
        if current_key is not None and key != current_key:
            raw = "".join(current_parts).strip()
            if not raw:
                raw = " ".join(part.strip() for part in current_parts if part.strip())
            if raw:
                lines.append(raw)
            current_parts = []
        current_key = key
        current_parts.append(item.text)
    if current_parts:
        raw = "".join(current_parts).strip()
        if not raw:
            raw = " ".join(part.strip() for part in current_parts if part.strip())
        if raw:
            lines.append(raw)

    block_ids = list(dict.fromkeys(item.block_id for item in selected))
    line_ids = list(dict.fromkeys(item.line_id for item in selected))
    ordered_span_ids = [item.span_id for item in selected]
    trace = CanonicalSourceTrace(
        layout_box_index=-1,
        layout_box_class=source_class,
        stage3_block_ids=block_ids,
        stage3_line_ids=line_ids,
        stage3_span_ids=ordered_span_ids,
        stage3_table_ids=[],
    )
    return "\n".join(lines).strip(), trace, _union_bboxes([item.bbox for item in selected])


def _element_stage3_span_ids(
    extraction: DocumentExtraction,
    page_number: int,
    element: CanonicalElement,
) -> list[str]:
    """Return the Stage-3 text spans represented by a canonical element.

    New Stage-4 schema 1.5 elements carry exact ``stage3_span_ids``. Older
    structures do not, so fall back to the same conservative span/geometry
    matching used by the correction resolver. Empty/whitespace spans are not
    treated as content that must be preserved.
    """
    raw_page = _raw_page(extraction, page_number)
    if raw_page is None:
        return []
    available = span_map(raw_page)
    exact = [span_id for span_id in element.source.stage3_span_ids if span_id in available and available[span_id].text.strip()]
    if exact:
        return list(dict.fromkeys(exact))
    return [
        item.span_id
        for item in iter_page_spans(raw_page)
        if item.text.strip() and _geometry_matches_region(item.bbox, element.bbox, threshold=0.35)
    ]


def _source_trace_for_bbox(extraction: DocumentExtraction, page_number: int, bbox: list[float], source_class: str) -> CanonicalSourceTrace:
    raw_page = _raw_page(extraction, page_number)
    if raw_page is None:
        return CanonicalSourceTrace(
            layout_box_index=-1,
            layout_box_class=source_class,
            stage3_block_ids=[],
            stage3_line_ids=[],
            stage3_span_ids=[],
            stage3_table_ids=[],
        )

    block_ids: list[str] = []
    for block in raw_page.blocks:
        if _geometry_matches_region(block.bbox, bbox, threshold=0.2):
            block_ids.append(block.block_id)

    matched_spans = [
        item for item in iter_page_spans(raw_page)
        if _geometry_matches_region(item.bbox, bbox, threshold=0.35)
    ]
    line_ids = list(dict.fromkeys(item.line_id for item in matched_spans))
    span_ids = [item.span_id for item in matched_spans]

    table_ids: list[str] = []
    for table in raw_page.tables:
        if _geometry_matches_region(table.bbox, bbox, threshold=0.2):
            table_ids.append(table.table_id)

    return CanonicalSourceTrace(
        layout_box_index=-1,
        layout_box_class=source_class,
        stage3_block_ids=block_ids,
        stage3_line_ids=line_ids,
        stage3_span_ids=span_ids,
        stage3_table_ids=table_ids,
    )


def _refine_recovered_definition_provenance(
    structure: StructuredDocument,
    extraction: DocumentExtraction,
) -> None:
    """Repair over-broad exact span traces in older recovered definition rows.

    Stage 4.5 must remain compatible with Stage-4 artifacts produced before
    recovered glossary children recomputed their own source trace.  Those old
    artifacts can make every term/text child claim the full parent block's span
    list. Reproject only known synthetic definition roles from their final bbox,
    preserve the original layout-box identity, and drop any Stage-3 span still
    claimed by more than one recovered child. A duplicated span is ambiguous,
    so keeping it as broad block evidence is safer than pretending exact
    ownership.
    """
    for page in structure.pages:
        candidates = [
            element for element in page.elements
            if element.role_source in RECOVERED_DEFINITION_ROLES
            and element.type in {"definition_term", "definition_text"}
        ]
        if not candidates:
            continue

        for element in candidates:
            old = element.source
            trace = _source_trace_for_bbox(
                extraction,
                page.page_number,
                element.bbox,
                old.layout_box_class,
            )
            trace.layout_box_index = old.layout_box_index
            trace.layout_box_class = old.layout_box_class
            element.source = trace

        owners: dict[str, list[CanonicalElement]] = {}
        for element in candidates:
            for span_id in element.source.stage3_span_ids:
                owners.setdefault(span_id, []).append(element)
        ambiguous = {span_id for span_id, elements in owners.items() if len(elements) > 1}
        if not ambiguous:
            continue

        raw_page = _raw_page(extraction, page.page_number)
        if raw_page is None:
            continue
        available = span_map(raw_page)
        for element in candidates:
            element.source.stage3_span_ids = [
                span_id for span_id in element.source.stage3_span_ids
                if span_id not in ambiguous
            ]
            retained_lines = {
                available[span_id].line_id
                for span_id in element.source.stage3_span_ids
                if span_id in available
            }
            element.source.stage3_line_ids = [
                line_id for line_id in element.source.stage3_line_ids
                if line_id in retained_lines
            ]


def _text_from_bbox(extraction: DocumentExtraction, page_number: int, bbox: list[float]) -> str:
    """Reconstruct text from Stage 3 spans intersecting a corrected region.

    Stage 4.5 never asks the user to retype content after moving, splitting, or
    drawing a box. Text is derived from the immutable Stage 3 spans. This keeps
    manual edits geometric/semantic while preserving extraction provenance.
    """
    raw_page = _raw_page(extraction, page_number)
    if raw_page is None:
        return ""

    lines: list[tuple[float, float, str]] = []
    seen: set[tuple[float, float, float, float, str]] = set()

    for block in raw_page.blocks:
        if getattr(block, "type", None) != "text":
            continue
        for line in block.lines:
            parts: list[tuple[float, str]] = []
            for span in line.spans:
                if not _geometry_matches_region(span.bbox, bbox, threshold=0.35):
                    continue
                text = span.text.strip()
                if not text:
                    continue
                key = (
                    round(span.bbox[0], 2), round(span.bbox[1], 2),
                    round(span.bbox[2], 2), round(span.bbox[3], 2), text,
                )
                if key in seen:
                    continue
                seen.add(key)
                parts.append((span.bbox[0], text))
            if parts:
                parts.sort(key=lambda item: item[0])
                line_text = " ".join(text for _, text in parts).strip()
                lines.append((line.bbox[1], line.bbox[0], line_text))

    lines.sort(key=lambda item: (round(item[0], 1), item[1]))
    return "\n".join(text for _, _, text in lines).strip()


def _partition_text_and_sources(
    extraction: DocumentExtraction,
    page_number: int,
    bboxes: list[list[float]],
    source_class: str,
) -> list[tuple[str, CanonicalSourceTrace]]:
    """Assign each Stage-3 span to at most one split result.

    Independent bbox text recovery can assign a boundary-crossing span to both
    halves of a split. For a split we instead choose one winning region per
    span and preserve the exact line/span provenance of that exclusive
    assignment.
    """
    raw_page = _raw_page(extraction, page_number)
    if raw_page is None:
        return [
            (
                "",
                CanonicalSourceTrace(
                    layout_box_index=-1,
                    layout_box_class=source_class,
                    stage3_block_ids=[],
                    stage3_line_ids=[],
                    stage3_span_ids=[],
                    stage3_table_ids=[],
                ),
            )
            for _ in bboxes
        ]

    assigned: list[list] = [[] for _ in bboxes]
    for item in iter_page_spans(raw_page):
        text = item.text.strip()
        if not text:
            continue
        candidates: list[tuple[float, int]] = []
        for index, bbox in enumerate(bboxes):
            intersection = _intersection_area(item.bbox, bbox)
            if intersection <= 0 and not _center_inside(bbox, item.bbox):
                continue
            score = intersection / max(_area(item.bbox), 1.0)
            score = max(score, _overlap_fraction_of_smaller(item.bbox, bbox))
            if _center_inside(item.bbox, bbox):
                score += 0.25
            if _center_inside(bbox, item.bbox):
                score += 0.1
            candidates.append((score, index))
        if not candidates:
            continue
        _, winner = max(candidates, key=lambda candidate: (candidate[0], -candidate[1]))
        assigned[winner].append(item)

    results: list[tuple[str, CanonicalSourceTrace]] = []
    for index, bbox in enumerate(bboxes):
        items = sorted(assigned[index], key=lambda item: (item.block_index, item.line_index, item.span_index))
        lines: list[str] = []
        current_key: tuple[int, int] | None = None
        current_parts: list[str] = []
        for item in items:
            key = (item.block_index, item.line_index)
            if current_key is not None and key != current_key:
                line_text = "".join(current_parts).strip()
                if not line_text:
                    line_text = " ".join(part.strip() for part in current_parts if part.strip())
                if line_text:
                    lines.append(line_text)
                current_parts = []
            current_key = key
            current_parts.append(item.text)
        if current_parts:
            line_text = "".join(current_parts).strip()
            if not line_text:
                line_text = " ".join(part.strip() for part in current_parts if part.strip())
            if line_text:
                lines.append(line_text)

        table_ids = [
            table.table_id
            for table in raw_page.tables
            if _geometry_matches_region(table.bbox, bbox, threshold=0.2)
        ]
        results.append((
            "\n".join(lines).strip(),
            CanonicalSourceTrace(
                layout_box_index=-1,
                layout_box_class=source_class,
                stage3_block_ids=list(dict.fromkeys(item.block_id for item in items)),
                stage3_line_ids=list(dict.fromkeys(item.line_id for item in items)),
                stage3_span_ids=[item.span_id for item in items],
                stage3_table_ids=table_ids,
            ),
        ))
    return results


def _element_body_text(element: CanonicalElement) -> str:
    if element.type not in CONTENT_TYPES:
        return ""
    if element.type == "table" and element.table and element.table.markdown:
        return element.table.markdown.strip()
    return element.text.strip()


def _find_index(elements: list[CanonicalElement], element_id: str) -> int:
    return next((index for index, element in enumerate(elements) if element.element_id == element_id), -1)


def _assert_unique_result_ids(
    elements: list[CanonicalElement],
    operation: CorrectionOperation,
    replaceable_source_ids: set[str] | None = None,
) -> None:
    """Reject duplicate/colliding result IDs before mutating page state."""
    replaceable_source_ids = replaceable_source_ids or set()
    result_ids = [spec.element_id for spec in operation.result_elements]
    if len(result_ids) != len(set(result_ids)):
        raise InvalidCorrectionError("Correction result element_ids must be unique within an operation.")
    existing = {element.element_id for element in elements if element.element_id not in replaceable_source_ids}
    collisions = sorted(existing.intersection(result_ids))
    if collisions:
        raise InvalidCorrectionError(f"Correction result element_id already exists: {', '.join(collisions)}")


def _union_bbox(elements: list[CanonicalElement]) -> list[float]:
    return [
        min(item.bbox[0] for item in elements),
        min(item.bbox[1] for item in elements),
        max(item.bbox[2] for item in elements),
        max(item.bbox[3] for item in elements),
    ]


def _validate_split(
    source: CanonicalElement,
    specs: list[CorrectionElementSpec],
    normalized_bboxes: list[list[float]],
) -> None:
    if source.type not in SAFE_SPLIT_TYPES:
        raise InvalidCorrectionError(
            f"Split is not supported for {source.type}. Relabel or use a dedicated semantic editor first."
        )
    allowed_types = {source.type}
    if source.type == "page_header":
        allowed_types.add("caption")
    if source.type == "page_footer":
        allowed_types.add("footnote")
    if any(spec.type not in allowed_types for spec in specs):
        raise InvalidCorrectionError("Split result semantic types are not compatible with the source element.")

    sx0, sy0, sx1, sy1 = source.bbox
    boundary_tolerance = 3.0
    for bbox in normalized_bboxes:
        if (
            bbox[0] < sx0 - boundary_tolerance
            or bbox[1] < sy0 - boundary_tolerance
            or bbox[2] > sx1 + boundary_tolerance
            or bbox[3] > sy1 + boundary_tolerance
        ):
            raise InvalidCorrectionError("Split result boxes must stay inside the source element bbox.")
    for index, first in enumerate(normalized_bboxes):
        for second in normalized_bboxes[index + 1:]:
            if _intersection_area(first, second) > 1.0:
                raise InvalidCorrectionError("Split result boxes must not overlap each other.")

    source_area = max(_area(source.bbox), 1.0)
    covered = sum(_intersection_area(source.bbox, bbox) for bbox in normalized_bboxes)
    if covered / source_area < 0.75:
        raise InvalidCorrectionError("Split result boxes must cover at least 75% of the source element.")


def _validate_merge(elements: list[CanonicalElement], source_elements: list[CanonicalElement]) -> None:
    if len({element.type for element in source_elements}) != 1:
        raise InvalidCorrectionError("Merge sources must have the same semantic type. Relabel them first if needed.")
    source_type = source_elements[0].type
    if source_type not in SAFE_SPLIT_MERGE_TYPES:
        raise InvalidCorrectionError(
            f"Merge is not supported for {source_type}. Use the dedicated semantic/table correction tools instead."
        )
    if len({element.section_id for element in source_elements}) > 1:
        raise InvalidCorrectionError("Merge sources must belong to the same section.")
    if source_type == "definition_text" and len({element.definition_entry_id for element in source_elements}) > 1:
        raise InvalidCorrectionError("Definition text from different definition entries cannot be merged.")

    source_ids = {element.element_id for element in source_elements}
    union = _union_bbox(source_elements)
    # A non-selected content element geometrically between selected boxes would
    # be swallowed by bbox-based text reconstruction and then remain separately,
    # duplicating content.  Reject that ambiguous merge rather than guessing.
    blockers = []
    for element in elements:
        if element.element_id in source_ids:
            continue
        if not element.text.strip() and element.table is None and element.type != "figure":
            continue
        if _center_inside(element.bbox, union) or _overlap_fraction_of_smaller(element.bbox, union) >= 0.55:
            blockers.append(element.element_id)
    if blockers:
        raise InvalidCorrectionError(
            "Merge selection is not contiguous; unselected content lies inside the merged region: "
            + ", ".join(blockers)
        )


def _validate_span_rebuild(
    elements: list[CanonicalElement],
    operation: CorrectionOperation,
    extraction: DocumentExtraction,
    page_number: int,
    width: float,
    height: float,
) -> tuple[list[CanonicalElement], list[tuple[CorrectionElementSpec, str, CanonicalSourceTrace, list[float]]]]:
    if not operation.result_elements:
        raise InvalidCorrectionError("Span rebuild requires at least one result element.")

    source_elements: list[CanonicalElement] = []
    for element_id in operation.source_element_ids:
        index = _find_index(elements, element_id)
        if index < 0:
            raise InvalidCorrectionError(f"Span rebuild source not found: {element_id}")
        source_elements.append(elements[index])
    if any(element.type not in SAFE_SPAN_REBUILD_TYPES for element in source_elements):
        invalid = sorted({element.type for element in source_elements if element.type not in SAFE_SPAN_REBUILD_TYPES})
        raise InvalidCorrectionError(
            "Span rebuild cannot replace record-bearing structural elements: " + ", ".join(invalid)
        )
    if any(spec.type not in SAFE_SPAN_REBUILD_TYPES for spec in operation.result_elements):
        invalid = sorted({spec.type for spec in operation.result_elements if spec.type not in SAFE_SPAN_REBUILD_TYPES})
        raise InvalidCorrectionError(
            "Span rebuild cannot create record-bearing structural elements: " + ", ".join(invalid)
        )

    _assert_unique_result_ids(elements, operation, set(operation.source_element_ids))

    seen_span_ids: set[str] = set()
    resolved_specs: list[tuple[CorrectionElementSpec, str, CanonicalSourceTrace, list[float]]] = []
    for spec in operation.result_elements:
        if not spec.source_span_ids:
            raise InvalidCorrectionError(f"Span rebuild result {spec.element_id} has no source_span_ids.")
        duplicates = seen_span_ids.intersection(spec.source_span_ids)
        if duplicates:
            raise InvalidCorrectionError(
                "The same Stage 3 span cannot be assigned to multiple span-rebuild results: "
                + ", ".join(sorted(duplicates))
            )
        seen_span_ids.update(spec.source_span_ids)
        text, trace, derived_bbox = _span_text_trace_and_bbox(
            extraction, page_number, spec.source_span_ids, "manual_span_rebuild"
        )
        normalized_submitted = _normalize_bbox(spec.bbox, width, height)
        normalized_derived = _normalize_bbox(derived_bbox, width, height)
        if not _bbox_close(normalized_submitted, normalized_derived):
            raise InvalidCorrectionError(
                f"Span-derived bbox for {spec.element_id} changed. Reload the span selection before saving."
            )
        if not text:
            raise InvalidCorrectionError(f"Span rebuild result {spec.element_id} resolves to empty text.")
        raw_page = _raw_page(extraction, page_number)
        assert raw_page is not None
        selected_set = set(spec.source_span_ids)
        skipped_inside = [
            item.span_id
            for item in iter_page_spans(raw_page)
            if item.text.strip() and item.span_id not in selected_set and _center_inside(item.bbox, normalized_derived)
        ]
        if skipped_inside:
            raise InvalidCorrectionError(
                f"Span selection for {spec.element_id} skips text inside its derived bbox: "
                + ", ".join(skipped_inside[:8])
                + ("…" if len(skipped_inside) > 8 else "")
            )
        resolved_specs.append((spec, text, trace, normalized_derived))

    replacing = set(operation.source_element_ids)
    selected_span_ids = set().union(*(set(spec.source_span_ids) for spec in operation.result_elements))

    # Span rebuild is a lossless repartition of any source canonical elements.
    # If only part of a source element is selected, the remaining source spans
    # must also appear in another result element (the frontend creates that
    # residual automatically). This prevents a precise term correction from
    # accidentally deleting the rest of a paragraph/definition block.
    required_source_span_ids: set[str] = set()
    unresolved_sources: list[str] = []
    for element in source_elements:
        source_span_ids = _element_stage3_span_ids(extraction, page_number, element)
        if element.text.strip() and not source_span_ids:
            unresolved_sources.append(element.element_id)
        required_source_span_ids.update(source_span_ids)
    if unresolved_sources:
        raise InvalidCorrectionError(
            "Cannot prove span coverage for source element(s): "
            + ", ".join(unresolved_sources)
            + ". Re-run Stage 3/4 or use element-level correction instead."
        )
    missing_source_spans = sorted(required_source_span_ids - selected_span_ids)
    if missing_source_spans:
        raise InvalidCorrectionError(
            "Span rebuild would discard unassigned source text. Preserve the remaining source spans in residual result element(s): "
            + ", ".join(missing_source_spans[:8])
            + ("…" if len(missing_source_spans) > 8 else "")
        )

    selected_union = _union_bboxes([bbox for _, _, _, bbox in resolved_specs])
    blockers: list[str] = []
    for element in elements:
        if element.element_id in replacing:
            continue
        exact_overlap = selected_span_ids.intersection(element.source.stage3_span_ids)
        geometry_overlap = (
            bool(element.text.strip())
            and (
                _center_inside(element.bbox, selected_union)
                or _overlap_fraction_of_smaller(element.bbox, selected_union) >= 0.65
            )
        )
        if exact_overlap or geometry_overlap:
            blockers.append(element.element_id)
    if blockers:
        raise InvalidCorrectionError(
            "Selected spans already belong to canonical content that is not being replaced: "
            + ", ".join(sorted(set(blockers)))
            + ". Add the overlapping element(s) as span-rebuild sources first."
        )

    return source_elements, resolved_specs


def _horizontal_overlap_fraction(a: list[float], b: list[float]) -> float:
    overlap = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    smaller_width = max(min(a[2] - a[0], b[2] - b[0]), 1.0)
    return overlap / smaller_width


def _reconcile_page_reading_order(elements: list[CanonicalElement], touched_ids: set[str]) -> None:
    """Reposition only geometry-edited elements against same-column anchors.

    A full y/x sort can silently destroy legitimate multi-column reading order.
    Instead, unchanged elements retain their exact relative order.  Each edited
    or newly-created element moves only when there is clear vertical separation
    from horizontally-overlapping anchors (roughly the same reading column).
    """
    if len(elements) < 2 or not touched_ids:
        return
    tolerance = 0.5
    for element_id in [item.element_id for item in list(elements) if item.element_id in touched_ids]:
        current_index = _find_index(elements, element_id)
        if current_index < 0:
            continue
        item = elements.pop(current_index)
        comparable = [
            (index, other)
            for index, other in enumerate(elements)
            if _horizontal_overlap_fraction(item.bbox, other.bbox) >= 0.2
        ]
        if not comparable:
            elements.insert(min(current_index, len(elements)), item)
            continue

        above = [
            index for index, other in comparable
            if other.bbox[3] <= item.bbox[1] + tolerance
        ]
        below = [
            index for index, other in comparable
            if item.bbox[3] <= other.bbox[1] + tolerance
        ]
        lower_bound = (max(above) + 1) if above else 0
        upper_bound = min(below) if below else len(elements)
        if lower_bound <= upper_bound:
            insert_at = min(max(current_index, lower_bound), upper_bound)
        else:
            # Conflicting anchors are a sign of overlapping/complex layout;
            # preserve the prior order rather than guessing.
            insert_at = min(current_index, len(elements))
        elements.insert(insert_at, item)


def _manual_definition_id(term_element_id: str) -> str:
    """Return a deterministic ID for a manually linked definition entry.

    Deterministic IDs keep undo/redo and repeated saves stable while avoiding a
    document-global counter that could collide with automatic ``def-N`` IDs.
    """
    safe = "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in term_element_id)
    return f"manual-def-{safe}"


def _spec_to_element(
    *,
    spec: CorrectionElementSpec,
    page_number: int,
    width: float,
    height: float,
    extraction: DocumentExtraction,
    template: CanonicalElement | None,
    role_source: str,
) -> CanonicalElement:
    requested_bbox = _normalize_bbox(spec.bbox, width, height)
    if spec.source_span_ids:
        text, source_trace, derived_bbox = _span_text_trace_and_bbox(
            extraction, page_number, spec.source_span_ids, role_source
        )
        bbox = _normalize_bbox(derived_bbox, width, height)
        if not _bbox_close(requested_bbox, bbox):
            raise InvalidCorrectionError(
                f"Span-derived bbox for {spec.element_id} does not match the submitted bbox. "
                "Reload the span selection before saving."
            )
    else:
        bbox = requested_bbox
        text = _text_from_bbox(extraction, page_number, bbox)
        source_trace = _source_trace_for_bbox(extraction, page_number, bbox, role_source)

    if template is not None:
        element = template.model_copy(deep=True)
        element.element_id = spec.element_id
        element.type = spec.type
        element.bbox = bbox
        element.text = text
        element.role_source = role_source
        element.table = template.table if spec.type == "table" else None
        # Preserve higher-order IDs only when the result retains the same role.
        if spec.type != template.type:
            if spec.type != "section_header":
                element.heading_level = None
                element.heading_level_source = None
            if spec.type not in {"clause", "subclause"}:
                element.clause_number = None
                element.clause_id = None
                element.parent_clause_id = None
                element.subclause_marker = None
            if spec.type not in {"definition_term", "definition_text"}:
                element.definition_entry_id = None
            if spec.type != "table":
                element.logical_table_id = None
            if spec.type != "figure":
                element.figure_id = None
        element.source = source_trace
        return element

    return CanonicalElement(
        element_id=spec.element_id,
        type=spec.type,
        page_number=page_number,
        reading_order=0,
        document_order=0,
        bbox=bbox,
        text=text,
        role_source=role_source,
        source=source_trace,
    )


def _apply_operation(
    elements: list[CanonicalElement],
    operation: CorrectionOperation,
    *,
    page_number: int,
    width: float,
    height: float,
    extraction: DocumentExtraction,
) -> None:
    if operation.page_number != page_number:
        return

    # Relationship operations are document-level graph edits. They are applied
    # only after every page-local element operation has finished so links can
    # safely target elements created by split/draw corrections.
    if operation.operation in RELATIONSHIP_OPERATIONS or operation.operation in DEFINITION_MEMBERSHIP_OPERATIONS:
        return

    if operation.operation == "relabel":
        if not operation.source_element_ids or operation.new_type is None:
            raise InvalidCorrectionError("Relabel requires at least one source element and a new_type.")
        if len(set(operation.source_element_ids)) != len(operation.source_element_ids):
            raise InvalidCorrectionError("Relabel source_element_ids must be unique.")

        target_indexes: list[int] = []
        for element_id in operation.source_element_ids:
            index = _find_index(elements, element_id)
            if index < 0:
                raise InvalidCorrectionError(f"Relabel source not found: {element_id}")
            target_indexes.append(index)

        # Generic correction may demote an existing structural element to a safe
        # leaf type, but it must not create new record-bearing structure.
        if operation.new_type in STRUCTURAL_PROMOTION_TYPES and any(
            elements[index].type != operation.new_type for index in target_indexes
        ):
            raise InvalidCorrectionError(
                f"Relabeling to {operation.new_type} requires a dedicated structural editor; "
                "the generic correction editor cannot safely create the associated canonical record."
            )

        for index in target_indexes:
            element = elements[index]
            old_type = element.type
            element.type = operation.new_type
            element.role_source = "manual_relabel"
            if old_type != operation.new_type:
                if operation.new_type != "section_header":
                    element.heading_level = None
                    element.heading_level_source = None
                if operation.new_type not in {"clause", "subclause"}:
                    element.clause_number = None
                    element.clause_id = None
                    element.parent_clause_id = None
                    element.subclause_marker = None
                if operation.new_type not in {"definition_term", "definition_text"}:
                    element.definition_entry_id = None
                if operation.new_type != "table":
                    element.logical_table_id = None
                    element.table = None
                if operation.new_type != "figure":
                    element.figure_id = None
        return

    if operation.operation == "delete":
        if not operation.source_element_ids:
            raise InvalidCorrectionError("Delete requires at least one source element.")
        missing = [element_id for element_id in operation.source_element_ids if _find_index(elements, element_id) < 0]
        if missing:
            raise InvalidCorrectionError(f"Delete source not found: {', '.join(missing)}")
        elements[:] = [element for element in elements if element.element_id not in set(operation.source_element_ids)]
        return

    if operation.operation == "move_resize":
        if len(operation.source_element_ids) != 1 or len(operation.result_elements) != 1:
            raise InvalidCorrectionError("Move/resize requires one source and one result element.")
        source_id = operation.source_element_ids[0]
        index = _find_index(elements, source_id)
        if index < 0:
            raise InvalidCorrectionError(f"Move/resize source not found: {source_id}")
        source = elements[index]
        spec = operation.result_elements[0]
        if spec.element_id != source_id:
            raise InvalidCorrectionError("Move/resize must keep the same element_id.")
        if spec.type != source.type:
            raise InvalidCorrectionError("Move/resize cannot change semantic type; use relabel separately.")
        elements[index] = _spec_to_element(
            spec=spec,
            page_number=page_number,
            width=width,
            height=height,
            extraction=extraction,
            template=source,
            role_source="manual_bbox",
        )
        return

    if operation.operation == "split":
        if len(operation.source_element_ids) != 1 or len(operation.result_elements) < 2:
            raise InvalidCorrectionError("Split requires one source and at least two result elements.")
        source_id = operation.source_element_ids[0]
        index = _find_index(elements, source_id)
        if index < 0:
            raise InvalidCorrectionError(f"Split source not found: {source_id}")
        source = elements[index]
        _assert_unique_result_ids(elements, operation, {source_id})
        normalized_bboxes = [_normalize_bbox(spec.bbox, width, height) for spec in operation.result_elements]
        _validate_split(source, operation.result_elements, normalized_bboxes)
        results = [
            _spec_to_element(
                spec=spec,
                page_number=page_number,
                width=width,
                height=height,
                extraction=extraction,
                template=source,
                role_source="manual_split",
            )
            for spec in operation.result_elements
        ]
        partitioned = _partition_text_and_sources(
            extraction,
            page_number,
            normalized_bboxes,
            "manual_split",
        )
        for result, (text, trace) in zip(results, partitioned):
            result.text = text
            result.source = trace
        results.sort(key=lambda item: (item.bbox[1], item.bbox[0]))
        elements[index:index + 1] = results
        return

    if operation.operation == "merge":
        if len(operation.source_element_ids) < 2 or len(operation.result_elements) != 1:
            raise InvalidCorrectionError("Merge requires at least two sources and exactly one result element.")
        indices = [_find_index(elements, element_id) for element_id in operation.source_element_ids]
        if any(index < 0 for index in indices):
            missing = [element_id for element_id, index in zip(operation.source_element_ids, indices) if index < 0]
            raise InvalidCorrectionError(f"Merge source not found: {', '.join(missing)}")
        source_elements = [elements[index] for index in indices]
        _validate_merge(elements, source_elements)
        _assert_unique_result_ids(elements, operation, set(operation.source_element_ids))
        insert_at = min(indices)
        template = source_elements[0]
        spec = operation.result_elements[0]
        if spec.type != template.type:
            raise InvalidCorrectionError("Merge result must keep the source semantic type. Relabel after merging if needed.")
        result = _spec_to_element(
            spec=spec,
            page_number=page_number,
            width=width,
            height=height,
            extraction=extraction,
            template=template,
            role_source="manual_merge",
        )
        source_set = set(operation.source_element_ids)
        elements[:] = [element for element in elements if element.element_id not in source_set]
        elements.insert(min(insert_at, len(elements)), result)
        return

    if operation.operation == "span_rebuild":
        source_elements, resolved_specs = _validate_span_rebuild(
            elements, operation, extraction, page_number, width, height
        )
        source_ids = set(operation.source_element_ids)
        source_index_by_id = {element.element_id: _find_index(elements, element.element_id) for element in source_elements}
        insert_at = min(source_index_by_id.values()) if source_index_by_id else len(elements)

        source_span_sets = {
            element.element_id: set(_element_stage3_span_ids(extraction, page_number, element))
            for element in source_elements
        }
        replacements: list[CanonicalElement] = []
        for spec, text, trace, bbox in resolved_specs:
            template = next((element for element in source_elements if element.element_id == spec.element_id), None)
            if template is None:
                spec_span_ids = set(spec.source_span_ids)
                owning_sources = [
                    element for element in source_elements
                    if spec_span_ids and spec_span_ids.issubset(source_span_sets.get(element.element_id, set()))
                ]
                if len(owning_sources) == 1:
                    template = owning_sources[0]
            if template is None and len(source_elements) == 1 and len(resolved_specs) == 1:
                template = source_elements[0]
            if template is not None:
                result = template.model_copy(deep=True)
                old_type = result.type
                result.element_id = spec.element_id
                result.type = spec.type
                result.bbox = bbox
                result.text = text
                result.role_source = "manual_span_rebuild"
                result.source = trace
                result.table = None
                if old_type != spec.type:
                    if spec.type != "section_header":
                        result.heading_level = None
                        result.heading_level_source = None
                    if spec.type not in {"clause", "subclause"}:
                        result.clause_number = None
                        result.clause_id = None
                        result.parent_clause_id = None
                        result.subclause_marker = None
                    if spec.type not in {"definition_term", "definition_text"} or (
                        old_type in {"definition_term", "definition_text"} and old_type != spec.type
                    ):
                        result.definition_entry_id = None
                    result.logical_table_id = None
                    result.figure_id = None
            else:
                prior = [
                    element for element in elements
                    if element.element_id not in source_ids
                    and element.section_id
                    and (element.bbox[1], element.bbox[0]) <= (bbox[1], bbox[0])
                ]
                section_id = prior[-1].section_id if prior else None
                result = CanonicalElement(
                    element_id=spec.element_id,
                    type=spec.type,
                    page_number=page_number,
                    reading_order=0,
                    document_order=0,
                    bbox=bbox,
                    text=text,
                    section_id=section_id,
                    role_source="manual_span_rebuild",
                    source=trace,
                )
            replacements.append(result)

        if source_ids:
            elements[:] = [element for element in elements if element.element_id not in source_ids]
            insert_at = min(insert_at, len(elements))
        else:
            first_bbox = min((item.bbox for item in replacements), key=lambda box: (box[1], box[0]))
            insert_at = next(
                (index for index, element in enumerate(elements) if (element.bbox[1], element.bbox[0]) > (first_bbox[1], first_bbox[0])),
                len(elements),
            )
        replacements.sort(key=lambda item: (item.bbox[1], item.bbox[0]))
        elements[insert_at:insert_at] = replacements
        return

    if operation.operation == "draw":
        if operation.source_element_ids or len(operation.result_elements) != 1:
            raise InvalidCorrectionError("Draw requires no source and exactly one result element.")
        spec = operation.result_elements[0]
        if spec.type not in SAFE_DRAW_TYPES:
            raise InvalidCorrectionError(
                f"Drawing a new {spec.type} element requires a dedicated structural editor; "
                "the generic correction editor cannot safely create the associated canonical record."
            )
        if _find_index(elements, spec.element_id) >= 0:
            raise InvalidCorrectionError(f"Draw result element_id already exists: {spec.element_id}")
        result = _spec_to_element(
            spec=spec,
            page_number=page_number,
            width=width,
            height=height,
            extraction=extraction,
            template=None,
            role_source="manual_draw",
        )
        # Insert by geometric reading order. Existing automatic order is otherwise preserved.
        insert_at = next(
            (index for index, element in enumerate(elements) if (element.bbox[1], element.bbox[0]) > (result.bbox[1], result.bbox[0])),
            len(elements),
        )
        elements.insert(insert_at, result)
        return

    raise InvalidCorrectionError(f"Unsupported correction operation: {operation.operation}")


def _relationship_from_spec(spec: CorrectionRelationshipSpec) -> StructuralRelation:
    return StructuralRelation(
        relation_id=spec.relation_id,
        type=spec.type,
        source_element_id=spec.source_element_id,
        target_element_id=spec.target_element_id,
        evidence=spec.evidence.strip() or "manual relationship correction",
        provenance="manual",
    )


def _apply_definition_membership_operations(
    structure: StructuredDocument,
    operations: list[CorrectionOperation],
) -> None:
    """Apply explicit definition membership selected by the reviewer.

    Stage 4.5.8.16 makes definition assignment intentionally simple:

    * ``assign_definition`` links one or more ``definition_text`` elements to
      an existing DefinitionEntry chosen by the reviewer.
    * the backend derives section membership from that DefinitionEntry; the
      reviewer never has to re-enter ``section_id``.
    * ``unassign_definition`` clears only definition membership and leaves the
      ordinary section relation intact.

    Legacy pair-wise ``link_definition`` / ``unlink_definition`` operations are
    still accepted so saved correction artifacts from earlier versions remain
    replayable.
    """
    element_by_id = {
        element.element_id: element
        for page in structure.pages
        for element in page.elements
    }
    page_by_id = {
        element.element_id: page.page_number
        for page in structure.pages
        for element in page.elements
    }
    definition_by_id = {entry.definition_id: entry for entry in structure.definitions}

    def definition_section(entry) -> str | None:
        term = element_by_id.get(entry.term_element_id) if entry.term_element_id else None
        return term.section_id if term is not None else entry.section_id

    for operation in operations:
        if operation.operation not in DEFINITION_MEMBERSHIP_OPERATIONS:
            continue

        if operation.operation in {"assign_definition", "unassign_definition"}:
            if operation.result_elements or operation.new_type is not None or operation.structure is not None:
                raise InvalidCorrectionError("Definition assignment cannot contain result elements, new_type, or structure payloads.")
            if not operation.source_element_ids:
                raise InvalidCorrectionError("Definition assignment requires at least one source element.")
            targets: list[CanonicalElement] = []
            for element_id in operation.source_element_ids:
                target = element_by_id.get(element_id)
                if target is None:
                    raise InvalidCorrectionError(f"Definition text source not found: {element_id}")
                if page_by_id[element_id] != operation.page_number:
                    raise InvalidCorrectionError("All selected definition-text elements must be on the correction page.")
                if target.type != "definition_text":
                    raise InvalidCorrectionError("Definition assignment only accepts definition_text elements.")
                targets.append(target)

            if operation.operation == "unassign_definition":
                for target in targets:
                    target.definition_entry_id = None
                    target.role_source = "manual_definition_unassign"
                continue

            definition_id = (operation.definition_id or "").strip()
            if not definition_id:
                raise InvalidCorrectionError("assign_definition requires definition_id.")
            entry = definition_by_id.get(definition_id)
            if entry is None:
                raise InvalidCorrectionError(f"DefinitionEntry not found: {definition_id}")
            if not entry.term_element_id:
                raise InvalidCorrectionError(f"DefinitionEntry {definition_id} has no term element.")
            term = element_by_id.get(entry.term_element_id)
            if term is None or term.type != "definition_term":
                raise InvalidCorrectionError(f"DefinitionEntry {definition_id} has an invalid definition term.")
            section_id = definition_section(entry)
            for target in targets:
                target.definition_entry_id = definition_id
                target.section_id = section_id
                target.role_source = "manual_definition_assign"
            continue

        # Backward compatibility for Stage 4.5.8.15 and earlier pair-wise ops.
        if len(operation.source_element_ids) != 2 or operation.result_elements or operation.new_type is not None:
            raise InvalidCorrectionError(
                "Definition membership correction requires exactly a term and definition-text source element."
            )
        term_id, text_id = operation.source_element_ids
        term = element_by_id.get(term_id)
        definition_text = element_by_id.get(text_id)
        if term is None:
            raise InvalidCorrectionError(f"Definition term source not found: {term_id}")
        if definition_text is None:
            raise InvalidCorrectionError(f"Definition text source not found: {text_id}")
        if page_by_id[term_id] != operation.page_number:
            raise InvalidCorrectionError("Definition correction page_number must match the term element page.")
        if operation.target_page_number is not None and page_by_id[text_id] != operation.target_page_number:
            raise InvalidCorrectionError("Definition correction target_page_number does not match the definition-text page.")
        if term.type != "definition_term":
            raise InvalidCorrectionError("Definition link source must be a definition_term element.")
        if definition_text.type != "definition_text":
            raise InvalidCorrectionError("Definition link target must be a definition_text element.")
        if term.element_id == definition_text.element_id:
            raise InvalidCorrectionError("A definition term cannot link to itself.")

        if operation.operation == "link_definition":
            definition_id = term.definition_entry_id or _manual_definition_id(term.element_id)
            term.definition_entry_id = definition_id
            definition_text.definition_entry_id = definition_id
            definition_text.section_id = term.section_id
            term.role_source = "manual_definition_link"
            definition_text.role_source = "manual_definition_link"
            continue

        if not term.definition_entry_id or definition_text.definition_entry_id != term.definition_entry_id:
            raise InvalidCorrectionError("The selected term and definition text are not currently linked.")
        definition_id = term.definition_entry_id
        definition_text.definition_entry_id = None
        definition_text.role_source = "manual_definition_unlink"
        if not any(
            element.type == "definition_text"
            and element.element_id != definition_text.element_id
            and element.definition_entry_id == definition_id
            for element in element_by_id.values()
        ):
            term.definition_entry_id = None
            term.role_source = "manual_definition_unlink"


def _apply_relationship_operations(
    structure: StructuredDocument,
    operations: list[CorrectionOperation],
) -> None:
    """Apply auditable manual graph edits after page-local corrections.

    The operation payload carries source/target page numbers for auditability,
    but the backend always verifies them against the final corrected elements.
    This prevents a pasted or stale correction JSON from linking the wrong
    element just because an ID happens to exist.
    """

    element_page = {
        element.element_id: page.page_number
        for page in structure.pages
        for element in page.elements
    }

    for operation in operations:
        if operation.operation not in RELATIONSHIP_OPERATIONS:
            continue

        if operation.source_element_ids or operation.result_elements or operation.new_type is not None:
            raise InvalidCorrectionError(
                f"{operation.operation} must use the relationships field only."
            )
        if not operation.relationships:
            raise InvalidCorrectionError(
                f"{operation.operation} requires at least one relationship snapshot."
            )
        unsupported_types = sorted({spec.type for spec in operation.relationships if spec.type not in MANUAL_RELATION_TYPES})
        if unsupported_types:
            raise InvalidCorrectionError(
                "These relationship types are derived from canonical records and must be corrected through their "
                "dedicated structural editor: " + ", ".join(unsupported_types)
            )

        if operation.operation == "add_relationship":
            existing_ids = {relation.relation_id for relation in structure.relationships}
            existing_edges = {
                (relation.type, relation.source_element_id, relation.target_element_id)
                for relation in structure.relationships
            }
            for spec in operation.relationships:
                if spec.relation_id in existing_ids:
                    raise InvalidCorrectionError(
                        f"Relationship ID already exists: {spec.relation_id}"
                    )
                if spec.source_element_id == spec.target_element_id:
                    raise InvalidCorrectionError("A relationship cannot link an element to itself.")
                if spec.source_element_id not in element_page:
                    raise InvalidCorrectionError(
                        f"Relationship source element not found: {spec.source_element_id}"
                    )
                if spec.target_element_id not in element_page:
                    raise InvalidCorrectionError(
                        f"Relationship target element not found: {spec.target_element_id}"
                    )

                actual_source_page = element_page[spec.source_element_id]
                actual_target_page = element_page[spec.target_element_id]
                if actual_source_page != spec.source_page_number or actual_target_page != spec.target_page_number:
                    raise InvalidCorrectionError(
                        "Relationship page metadata does not match the corrected element locations."
                    )
                if operation.page_number != actual_source_page:
                    raise InvalidCorrectionError(
                        "Relationship correction page_number must match the source element page."
                    )

                edge = (spec.type, spec.source_element_id, spec.target_element_id)
                if edge in existing_edges:
                    raise InvalidCorrectionError(
                        "An equivalent relationship already exists between these elements."
                    )

                if spec.type == "continues":
                    if actual_source_page >= actual_target_page:
                        raise InvalidCorrectionError(
                            "A manual continues relationship must point forward to a later page."
                        )

                relation = _relationship_from_spec(spec)
                structure.relationships.append(relation)
                existing_ids.add(spec.relation_id)
                existing_edges.add(edge)
            continue

        # remove_relationship snapshots keep the correction log self-contained.
        # Only the relation_id is used to identify the automatic/manual edge;
        # endpoints are checked as a guard against deleting the wrong relation.
        for spec in operation.relationships:
            index = next(
                (
                    idx for idx, relation in enumerate(structure.relationships)
                    if relation.relation_id == spec.relation_id
                ),
                -1,
            )
            if index < 0:
                raise InvalidCorrectionError(
                    f"Relationship to remove was not found: {spec.relation_id}"
                )
            relation = structure.relationships[index]
            if (
                relation.type != spec.type
                or relation.source_element_id != spec.source_element_id
                or relation.target_element_id != spec.target_element_id
            ):
                raise InvalidCorrectionError(
                    f"Relationship snapshot does not match {spec.relation_id}."
                )
            structure.relationships.pop(index)


def _record_id_unique(records: list, attr: str, value: str, element_id: str | None = None) -> bool:
    for record in records:
        if getattr(record, attr) != value:
            continue
        if element_id is not None and getattr(record, "element_id", None) == element_id:
            continue
        return False
    return True


def _apply_structural_operations(
    structure: StructuredDocument,
    operations: list[CorrectionOperation],
) -> None:
    """Apply intent-level section/clause/subclause corrections.

    These operations are deliberately document-level.  They update the element
    and its canonical record together so the frontend never has to hand-edit
    foreign-key-like fields independently.
    """

    element_by_id = {
        element.element_id: element
        for page in structure.pages
        for element in page.elements
    }
    page_by_id = {element.element_id: element.page_number for element in element_by_id.values()}

    for operation in operations:
        if operation.operation not in STRUCTURAL_OPERATIONS:
            continue
        if (
            operation.structure is None
            or operation.relationships
            or operation.result_elements
            or operation.new_type is not None
            or len(operation.source_element_ids) != 1
        ):
            raise InvalidCorrectionError(
                "set_structure requires exactly one source_element_id and one structure payload only."
            )

        spec = operation.structure
        source_id = operation.source_element_ids[0]
        if spec.element_id != source_id:
            raise InvalidCorrectionError("Structural correction element_id must match the source element_id.")
        element = element_by_id.get(source_id)
        if element is None:
            raise InvalidCorrectionError(f"Structural correction source not found: {source_id}")
        if page_by_id[source_id] != operation.page_number:
            raise InvalidCorrectionError("Structural correction page_number must match the source element page.")

        # A structured correction owns all role-specific fields.  Clear stale
        # memberships before writing the new canonical intent.
        element.type = spec.type
        element.role_source = "manual_structural_review"
        element.definition_entry_id = None
        element.logical_table_id = None
        element.figure_id = None
        element.table = None
        element.appendix_id = None

        if spec.type == "section_header":
            if not spec.section_id or not spec.section_id.strip():
                raise InvalidCorrectionError("Section correction requires a non-empty section_id.")
            if spec.clause_id or spec.clause_number or spec.parent_clause_id or spec.subclause_marker:
                raise InvalidCorrectionError("Section correction cannot contain clause fields.")
            if not _record_id_unique(structure.sections, "section_id", spec.section_id, element.element_id):
                raise InvalidCorrectionError(f"Section ID already belongs to another element: {spec.section_id}")
            if spec.parent_section_id == spec.section_id:
                raise InvalidCorrectionError("A section cannot be its own parent.")

            element.section_id = spec.section_id
            element.heading_level = spec.heading_level
            element.heading_level_source = "unknown"
            element.clause_number = None
            element.clause_id = None
            element.parent_clause_id = None
            element.subclause_marker = None

            existing = next((record for record in structure.sections if record.element_id == element.element_id), None)
            if existing is None:
                existing = SectionRecord(
                    section_id=spec.section_id,
                    title=element.text.strip() or "Untitled section",
                    level=spec.heading_level,
                    page_number=element.page_number,
                    element_id=element.element_id,
                    parent_section_id=spec.parent_section_id,
                    level_source="unknown",
                    kind=spec.section_kind,
                    content_element_ids=[],
                )
                structure.sections.append(existing)
            else:
                old_section_id = existing.section_id
                if old_section_id != spec.section_id:
                    for candidate in element_by_id.values():
                        if candidate.section_id == old_section_id:
                            candidate.section_id = spec.section_id
                    for candidate in structure.sections:
                        if candidate.parent_section_id == old_section_id:
                            candidate.parent_section_id = spec.section_id
                    for candidate in structure.clauses:
                        if candidate.section_id == old_section_id:
                            candidate.section_id = spec.section_id
                    for candidate in structure.tables:
                        if candidate.section_id == old_section_id:
                            candidate.section_id = spec.section_id
                    for candidate in structure.figures:
                        if candidate.section_id == old_section_id:
                            candidate.section_id = spec.section_id
                existing.section_id = spec.section_id
                existing.title = element.text.strip() or existing.title
                existing.level = spec.heading_level
                existing.page_number = element.page_number
                existing.parent_section_id = spec.parent_section_id
                existing.level_source = "unknown"
                existing.kind = spec.section_kind
            continue

        if spec.type == "clause":
            if not spec.clause_id or not spec.clause_id.strip():
                raise InvalidCorrectionError("Clause correction requires a non-empty clause_id.")
            if not spec.clause_number or not spec.clause_number.strip():
                raise InvalidCorrectionError("Clause correction requires a clause_number.")
            if spec.subclause_marker:
                raise InvalidCorrectionError("Clause correction cannot contain a subclause_marker.")
            if not _record_id_unique(structure.clauses, "clause_id", spec.clause_id, element.element_id):
                raise InvalidCorrectionError(f"Clause ID already belongs to another element: {spec.clause_id}")
            if spec.parent_clause_id == spec.clause_id:
                raise InvalidCorrectionError("A clause cannot be its own parent.")

            element.section_id = spec.section_id
            element.heading_level = None
            element.heading_level_source = None
            element.clause_id = spec.clause_id
            element.clause_number = spec.clause_number.strip()
            element.parent_clause_id = spec.parent_clause_id
            element.subclause_marker = None

            existing = next((record for record in structure.clauses if record.element_id == element.element_id), None)
            if existing is None:
                existing = ClauseRecord(
                    clause_id=spec.clause_id,
                    number=spec.clause_number.strip(),
                    kind="clause",
                    element_id=element.element_id,
                    page_number=element.page_number,
                    section_id=spec.section_id,
                    parent_clause_id=spec.parent_clause_id,
                )
                structure.clauses.append(existing)
            else:
                old_clause_id = existing.clause_id
                if old_clause_id != spec.clause_id:
                    for candidate in element_by_id.values():
                        if candidate.parent_clause_id == old_clause_id:
                            candidate.parent_clause_id = spec.clause_id
                    for candidate in structure.clauses:
                        if candidate.parent_clause_id == old_clause_id:
                            candidate.parent_clause_id = spec.clause_id
                existing.clause_id = spec.clause_id
                existing.number = spec.clause_number.strip()
                existing.kind = "clause"
                existing.page_number = element.page_number
                existing.section_id = spec.section_id
                existing.parent_clause_id = spec.parent_clause_id
            continue

        if spec.type == "subclause":
            if not spec.clause_id or not spec.clause_id.strip():
                raise InvalidCorrectionError("Subclause correction requires a non-empty clause_id.")
            if not spec.subclause_marker or not spec.subclause_marker.strip():
                raise InvalidCorrectionError("Subclause correction requires a subclause_marker.")
            if not spec.parent_clause_id or not spec.parent_clause_id.strip():
                raise InvalidCorrectionError("Subclause correction requires a parent_clause_id.")
            if spec.parent_clause_id == spec.clause_id:
                raise InvalidCorrectionError("A subclause cannot be its own parent.")
            if not _record_id_unique(structure.clauses, "clause_id", spec.clause_id, element.element_id):
                raise InvalidCorrectionError(f"Clause ID already belongs to another element: {spec.clause_id}")

            element.section_id = spec.section_id
            element.heading_level = None
            element.heading_level_source = None
            element.clause_id = spec.clause_id
            element.clause_number = None
            element.parent_clause_id = spec.parent_clause_id
            element.subclause_marker = spec.subclause_marker.strip()

            existing = next((record for record in structure.clauses if record.element_id == element.element_id), None)
            if existing is None:
                existing = ClauseRecord(
                    clause_id=spec.clause_id,
                    number=spec.subclause_marker.strip(),
                    kind="subclause",
                    element_id=element.element_id,
                    page_number=element.page_number,
                    section_id=spec.section_id,
                    parent_clause_id=spec.parent_clause_id,
                )
                structure.clauses.append(existing)
            else:
                old_clause_id = existing.clause_id
                if old_clause_id != spec.clause_id:
                    for candidate in element_by_id.values():
                        if candidate.parent_clause_id == old_clause_id:
                            candidate.parent_clause_id = spec.clause_id
                    for candidate in structure.clauses:
                        if candidate.parent_clause_id == old_clause_id:
                            candidate.parent_clause_id = spec.clause_id
                existing.clause_id = spec.clause_id
                existing.number = spec.subclause_marker.strip()
                existing.kind = "subclause"
                existing.page_number = element.page_number
                existing.section_id = spec.section_id
                existing.parent_clause_id = spec.parent_clause_id


def _rebuild_section_content_membership(structure: StructuredDocument) -> None:
    """Rebuild section.content_element_ids from element.section_id backrefs."""
    section_by_id = {section.section_id: section for section in structure.sections}
    for section in structure.sections:
        section.content_element_ids = []
    for page in structure.pages:
        for element in page.elements:
            if element.type == "section_header":
                continue
            if element.section_id and element.section_id in section_by_id:
                section_by_id[element.section_id].content_element_ids.append(element.element_id)


def _rebuild_derived_hierarchy_relations(structure: StructuredDocument) -> None:
    """Rebuild every record-derived hierarchy edge from canonical records.

    ``belongs_to`` and ``parent_of`` are projections of Section/Clause/Appendix
    records, not free-form Stage 4.5 edges. Removing all previous projections
    first prevents a relabel/delete from leaving a stale relation whose two
    endpoint IDs still happen to exist.
    """
    element_by_id = {element.element_id: element for page in structure.pages for element in page.elements}
    section_by_id = {section.section_id: section for section in structure.sections}
    clause_by_id = {clause.clause_id: clause for clause in structure.clauses}

    kept: list[StructuralRelation] = [
        relation for relation in structure.relationships
        if relation.type not in {"belongs_to", "parent_of"}
    ]
    existing_ids = {relation.relation_id for relation in kept}
    existing_edges = {(relation.type, relation.source_element_id, relation.target_element_id) for relation in kept}

    def append_relation(relation_id: str, relation_type: str, source: str, target: str, evidence: str) -> None:
        if source not in element_by_id or target not in element_by_id:
            return
        edge = (relation_type, source, target)
        if edge in existing_edges:
            return
        candidate = relation_id
        suffix = 2
        while candidate in existing_ids:
            candidate = f"{relation_id}-{suffix}"
            suffix += 1
        kept.append(StructuralRelation(
            relation_id=candidate,
            type=relation_type,
            source_element_id=source,
            target_element_id=target,
            evidence=evidence,
            provenance="derived",
        ))
        existing_ids.add(candidate)
        existing_edges.add(edge)

    for clause in structure.clauses:
        if clause.kind == "clause" and clause.section_id and clause.section_id in section_by_id:
            append_relation(
                f"rel-structure-{clause.clause_id}-section",
                "belongs_to",
                clause.element_id,
                section_by_id[clause.section_id].element_id,
                "canonical clause section membership",
            )
        if clause.parent_clause_id and clause.parent_clause_id in clause_by_id:
            parent = clause_by_id[clause.parent_clause_id]
            append_relation(
                f"rel-structure-{clause.clause_id}-parent",
                "parent_of",
                parent.element_id,
                clause.element_id,
                "canonical clause parent membership",
            )

    for appendix in structure.appendices:
        if appendix.title_element_id:
            append_relation(
                f"rel-structure-{appendix.appendix_id}-title",
                "belongs_to",
                appendix.title_element_id,
                appendix.label_element_id,
                "canonical appendix title membership",
            )

    structure.relationships = kept


def _rebuild_figure_relations(structure: StructuredDocument) -> None:
    """Rebuild figure-derived edges from surviving FigureRecord membership.

    Both endpoints of a stale figure edge may survive a correction, so simply
    removing dangling relationships is not enough. These four relation types
    are canonical figure projections and are regenerated here from the record.
    """
    element_by_id = {element.element_id: element for page in structure.pages for element in page.elements}
    figure_relation_types = {"introduces", "caption_of", "explains", "source_for"}
    kept: list[StructuralRelation] = [
        relation for relation in structure.relationships
        if relation.type not in figure_relation_types
    ]
    existing_ids = {relation.relation_id for relation in kept}
    existing_edges = {(relation.type, relation.source_element_id, relation.target_element_id) for relation in kept}

    def append_relation(relation_id: str, relation_type: str, source: str, target: str, evidence: str) -> None:
        if source not in element_by_id or target not in element_by_id:
            return
        edge = (relation_type, source, target)
        if edge in existing_edges:
            return
        candidate = relation_id
        suffix = 2
        while candidate in existing_ids:
            candidate = f"{relation_id}-{suffix}"
            suffix += 1
        kept.append(StructuralRelation(
            relation_id=candidate,
            type=relation_type,
            source_element_id=source,
            target_element_id=target,
            evidence=evidence,
            provenance="derived",
        ))
        existing_ids.add(candidate)
        existing_edges.add(edge)

    for figure in structure.figures:
        target = figure.element_id
        for source in figure.intro_element_ids:
            append_relation(
                f"rel-figure-{figure.figure_id}-intro-{source}",
                "introduces", source, target, "canonical figure introduction membership",
            )
        for source in figure.caption_element_ids:
            append_relation(
                f"rel-figure-{figure.figure_id}-caption-{source}",
                "caption_of", source, target, "canonical figure caption membership",
            )
        for source in figure.explanation_element_ids:
            append_relation(
                f"rel-figure-{figure.figure_id}-explanation-{source}",
                "explains", source, target, "canonical figure explanation membership",
            )
        for source in figure.source_element_ids:
            append_relation(
                f"rel-figure-{figure.figure_id}-source-{source}",
                "source_for", source, target, "canonical figure source membership",
            )

    structure.relationships = kept


def _rebuild_record_backed_continuation_relations(structure: StructuredDocument) -> None:
    """Rebuild table/definition ``continues`` edges from canonical membership.

    Open paragraph/clause/list continuations remain evidence-based edges and are
    preserved. Tables and definitions have explicit record membership, so their
    cross-page relations can and should be derived rather than independently
    edited JSON.
    """
    element_by_id = {element.element_id: element for page in structure.pages for element in page.elements}
    kept: list[StructuralRelation] = []
    for relation in structure.relationships:
        if relation.type != "continues":
            kept.append(relation)
            continue
        source = element_by_id.get(relation.source_element_id)
        target = element_by_id.get(relation.target_element_id)
        record_backed = (
            relation.evidence.startswith("adjacent-page tables")
            or relation.evidence.startswith("cross-page definition continuation")
            or (source is not None and source.type in {"table", "definition_text"})
            or (target is not None and target.type in {"table", "definition_text"})
        )
        if not record_backed:
            kept.append(relation)

    existing_ids = {relation.relation_id for relation in kept}
    existing_edges = {(relation.type, relation.source_element_id, relation.target_element_id) for relation in kept}

    def append_relation(relation_id: str, source: str, target: str, evidence: str) -> None:
        if source not in element_by_id or target not in element_by_id:
            return
        edge = ("continues", source, target)
        if edge in existing_edges:
            return
        candidate = relation_id
        suffix = 2
        while candidate in existing_ids:
            candidate = f"{relation_id}-{suffix}"
            suffix += 1
        kept.append(StructuralRelation(
            relation_id=candidate,
            type="continues",
            source_element_id=source,
            target_element_id=target,
            evidence=evidence,
            provenance="derived",
        ))
        existing_ids.add(candidate)
        existing_edges.add(edge)

    for table in structure.tables:
        fragments = [element_by_id.get(element_id) for element_id in table.fragment_element_ids]
        fragments = [element for element in fragments if element is not None and element.type == "table"]
        fragments.sort(key=lambda element: element.document_order)
        for left, right in zip(fragments, fragments[1:]):
            if left.page_number == right.page_number:
                continue
            append_relation(
                f"rel-table-{table.logical_table_id}-{left.element_id}-{right.element_id}",
                left.element_id,
                right.element_id,
                "canonical logical-table cross-page continuation",
            )

    for definition in structure.definitions:
        members = [element_by_id.get(element_id) for element_id in definition.definition_element_ids]
        members = [
            element for element in members
            if element is not None
            and element.type == "definition_text"
            and element.definition_entry_id == definition.definition_id
        ]
        members.sort(key=lambda element: element.document_order)
        for left, right in zip(members, members[1:]):
            if left.page_number == right.page_number:
                continue
            append_relation(
                f"rel-definition-{definition.definition_id}-{left.element_id}-{right.element_id}",
                left.element_id,
                right.element_id,
                "canonical definition cross-page continuation",
            )

    structure.relationships = kept

def _validate_structural_intents_before_reconcile(
    structure: StructuredDocument,
    operations: list[CorrectionOperation],
) -> None:
    """Reject invalid manually supplied foreign keys before cleanup can mask them."""
    specs = [
        operation.structure
        for operation in operations
        if operation.operation == "set_structure" and operation.structure is not None
    ]
    if not specs:
        return
    section_by_id = {section.section_id: section for section in structure.sections}
    clause_by_id = {clause.clause_id: clause for clause in structure.clauses}
    touched_section_ids = {spec.section_id for spec in specs if spec.type == "section_header" and spec.section_id}
    touched_clause_ids = {spec.clause_id for spec in specs if spec.type in {"clause", "subclause"} and spec.clause_id}

    section_cycle = _graph_cycle(
        set(section_by_id),
        {section_id: record.parent_section_id for section_id, record in section_by_id.items()},
    )
    if section_cycle:
        raise InvalidCorrectionError("Section hierarchy cycle: " + " → ".join(section_cycle))
    for section in structure.sections:
        if section.section_id not in touched_section_ids:
            continue
        if section.parent_section_id and section.parent_section_id not in section_by_id:
            raise InvalidCorrectionError(
                f"Section {section.section_id} references missing parent section {section.parent_section_id}."
            )

    clause_cycle = _graph_cycle(
        set(clause_by_id),
        {clause_id: record.parent_clause_id for clause_id, record in clause_by_id.items()},
    )
    if clause_cycle:
        raise InvalidCorrectionError("Clause hierarchy cycle: " + " → ".join(clause_cycle))
    for clause in structure.clauses:
        if clause.clause_id not in touched_clause_ids:
            continue
        if clause.section_id and clause.section_id not in section_by_id:
            raise InvalidCorrectionError(
                f"Clause {clause.clause_id} references missing section {clause.section_id}."
            )
        if clause.parent_clause_id:
            parent = clause_by_id.get(clause.parent_clause_id)
            if parent is None:
                raise InvalidCorrectionError(
                    f"Clause {clause.clause_id} references missing parent clause {clause.parent_clause_id}."
                )
            if clause.section_id and parent.section_id and clause.section_id != parent.section_id:
                raise InvalidCorrectionError(
                    f"Clause {clause.clause_id} and parent {parent.clause_id} belong to different sections."
                )
        if clause.kind == "subclause" and not clause.parent_clause_id:
            raise InvalidCorrectionError(f"Subclause {clause.clause_id} requires a parent clause.")


def _existing_element_ids(structure: StructuredDocument) -> set[str]:
    return {element.element_id for page in structure.pages for element in page.elements}


def _assert_global_unique_element_ids(structure: StructuredDocument) -> None:
    ids = [element.element_id for page in structure.pages for element in page.elements]
    duplicates = sorted(element_id for element_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise InvalidCorrectionError(
            "Resolved structure contains duplicate element_id values: " + ", ".join(duplicates)
        )


def _duplicate_values(values: list[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def _graph_cycle(nodes: set[str], parent_by_id: dict[str, str | None]) -> list[str] | None:
    """Return one cycle path if a single-parent graph contains a cycle."""
    visited: set[str] = set()
    for start in nodes:
        if start in visited:
            continue
        path: list[str] = []
        index_by_node: dict[str, int] = {}
        current: str | None = start
        while current is not None and current in nodes:
            if current in index_by_node:
                return path[index_by_node[current]:] + [current]
            if current in visited:
                break
            index_by_node[current] = len(path)
            path.append(current)
            current = parent_by_id.get(current)
        visited.update(path)
    return None


def _relationship_integrity_report(structure: StructuredDocument) -> RelationshipIntegrityReport:
    """Validate the resolved canonical graph like foreign keys plus hierarchy rules."""
    errors: list[IntegrityIssue] = []
    warnings: list[IntegrityIssue] = []

    def make_issue_id(code: str, message: str, element_ids: list[str], record_ids: list[str]) -> str:
        payload = "|".join([code, *sorted(element_ids), *sorted(record_ids), message])
        return f"ri-{sha256(payload.encode('utf-8')).hexdigest()[:16]}"

    def error(code: str, message: str, *, element_ids: list[str] | None = None, record_ids: list[str] | None = None) -> None:
        element_ids = element_ids or []
        record_ids = record_ids or []
        errors.append(IntegrityIssue(
            issue_id=make_issue_id(code, message, element_ids, record_ids),
            code=code,
            severity="error",
            message=message,
            element_ids=element_ids,
            record_ids=record_ids,
            requires_review=False,
        ))

    def warning(code: str, message: str, *, element_ids: list[str] | None = None, record_ids: list[str] | None = None, requires_review: bool | None = None) -> None:
        element_ids = element_ids or []
        record_ids = record_ids or []
        review = code in REVIEW_REQUIRED_WARNING_CODES if requires_review is None else requires_review
        warnings.append(IntegrityIssue(
            issue_id=make_issue_id(code, message, element_ids, record_ids),
            code=code,
            severity="warning",
            message=message,
            element_ids=element_ids,
            record_ids=record_ids,
            requires_review=review,
        ))

    elements = [element for page in structure.pages for element in page.elements]
    element_by_id = {element.element_id: element for element in elements}
    ids = set(element_by_id)

    duplicate_element_ids = _duplicate_values([element.element_id for element in elements])
    if duplicate_element_ids:
        error("duplicate_element_id", "Duplicate element IDs exist.", record_ids=duplicate_element_ids)

    section_by_id = {section.section_id: section for section in structure.sections}
    duplicate_section_ids = _duplicate_values([section.section_id for section in structure.sections])
    if duplicate_section_ids:
        error("duplicate_section_id", "Duplicate section IDs exist.", record_ids=duplicate_section_ids)
    for section in structure.sections:
        source = element_by_id.get(section.element_id)
        if source is None:
            error("section_source_missing", f"Section {section.section_id} points to a missing element.", record_ids=[section.section_id], element_ids=[section.element_id])
            continue
        if source.type != "section_header":
            error("section_source_type", f"Section {section.section_id} source is not a section_header.", record_ids=[section.section_id], element_ids=[source.element_id])
        if source.section_id != section.section_id:
            error("section_backref_mismatch", f"Section {section.section_id} and its header element disagree on section_id.", record_ids=[section.section_id], element_ids=[source.element_id])
        if source.page_number != section.page_number:
            error("section_page_mismatch", f"Section {section.section_id} page_number disagrees with its source header.", record_ids=[section.section_id], element_ids=[source.element_id])
        if section.parent_section_id:
            if section.parent_section_id not in section_by_id:
                error("section_parent_missing", f"Section {section.section_id} references missing parent {section.parent_section_id}.", record_ids=[section.section_id, section.parent_section_id])
            elif section.parent_section_id == section.section_id:
                error("section_self_parent", f"Section {section.section_id} cannot parent itself.", record_ids=[section.section_id])
            else:
                parent_section = section_by_id[section.parent_section_id]
                parent_source = element_by_id.get(parent_section.element_id)
                if parent_source is not None and parent_source.document_order >= source.document_order:
                    error(
                        "section_parent_not_before_child",
                        f"Parent section {parent_section.section_id} does not occur before child section {section.section_id}.",
                        record_ids=[parent_section.section_id, section.section_id],
                        element_ids=[parent_source.element_id, source.element_id],
                    )
                if parent_section.level is not None and section.level is not None and section.level <= parent_section.level:
                    warning(
                        "section_level_conflict",
                        f"Child section {section.section_id} has level {section.level}, which is not deeper than parent {parent_section.section_id} level {parent_section.level}.",
                        record_ids=[parent_section.section_id, section.section_id],
                        element_ids=[parent_section.element_id, section.element_id],
                    )
        seen_content: set[str] = set()
        for element_id in section.content_element_ids:
            if element_id in seen_content:
                error("section_duplicate_content", f"Section {section.section_id} contains duplicate element membership {element_id}.", record_ids=[section.section_id], element_ids=[element_id])
                continue
            seen_content.add(element_id)
            member = element_by_id.get(element_id)
            if member is None:
                error("section_content_missing", f"Section {section.section_id} references missing content element {element_id}.", record_ids=[section.section_id], element_ids=[element_id])
            elif member.section_id != section.section_id:
                error("section_content_backref_mismatch", f"Element {element_id} does not point back to section {section.section_id}.", record_ids=[section.section_id], element_ids=[element_id])
    cycle = _graph_cycle(set(section_by_id), {sid: record.parent_section_id for sid, record in section_by_id.items()})
    if cycle:
        error("section_cycle", "Section parent hierarchy contains a cycle: " + " → ".join(cycle), record_ids=cycle)
    for element in elements:
        if element.section_id and element.section_id not in section_by_id:
            error("element_section_missing", f"Element {element.element_id} references missing section {element.section_id}.", element_ids=[element.element_id], record_ids=[element.section_id])
        elif element.section_id and element.type != "section_header":
            section = section_by_id[element.section_id]
            if element.element_id not in section.content_element_ids:
                error("element_section_membership_missing", f"Element {element.element_id} points to section {element.section_id} but is absent from content_element_ids.", element_ids=[element.element_id], record_ids=[element.section_id])

    clause_by_id = {clause.clause_id: clause for clause in structure.clauses}
    duplicate_clause_ids = _duplicate_values([clause.clause_id for clause in structure.clauses])
    if duplicate_clause_ids:
        error("duplicate_clause_id", "Duplicate clause IDs exist.", record_ids=duplicate_clause_ids)
    for clause in structure.clauses:
        source = element_by_id.get(clause.element_id)
        if source is None:
            error("clause_source_missing", f"Clause {clause.clause_id} points to a missing element.", record_ids=[clause.clause_id], element_ids=[clause.element_id])
            continue
        if source.type != clause.kind:
            error("clause_source_type", f"Clause {clause.clause_id} expects {clause.kind} but source element is {source.type}.", record_ids=[clause.clause_id], element_ids=[source.element_id])
        if source.clause_id != clause.clause_id:
            error("clause_backref_mismatch", f"Clause {clause.clause_id} and source element disagree on clause_id.", record_ids=[clause.clause_id], element_ids=[source.element_id])
        if source.page_number != clause.page_number:
            error("clause_page_mismatch", f"Clause {clause.clause_id} page_number disagrees with its source element.", record_ids=[clause.clause_id], element_ids=[source.element_id])
        if source.section_id != clause.section_id:
            error("clause_section_mismatch", f"Clause {clause.clause_id} and source element disagree on section_id.", record_ids=[clause.clause_id], element_ids=[source.element_id])
        if clause.section_id and clause.section_id not in section_by_id:
            error("clause_section_missing", f"Clause {clause.clause_id} references missing section {clause.section_id}.", record_ids=[clause.clause_id, clause.section_id])
        if clause.parent_clause_id:
            parent = clause_by_id.get(clause.parent_clause_id)
            if parent is None:
                error("clause_parent_missing", f"Clause {clause.clause_id} references missing parent {clause.parent_clause_id}.", record_ids=[clause.clause_id, clause.parent_clause_id])
            elif parent.clause_id == clause.clause_id:
                error("clause_self_parent", f"Clause {clause.clause_id} cannot parent itself.", record_ids=[clause.clause_id])
            else:
                parent_source = element_by_id.get(parent.element_id)
                if parent_source is not None and parent_source.document_order >= source.document_order:
                    error(
                        "clause_parent_not_before_child",
                        f"Parent clause {parent.clause_id} does not occur before child {clause.clause_id}.",
                        record_ids=[parent.clause_id, clause.clause_id],
                        element_ids=[parent.element_id, source.element_id],
                    )
                if clause.section_id and parent.section_id and clause.section_id != parent.section_id:
                    error("clause_parent_section_conflict", f"Clause {clause.clause_id} and parent {parent.clause_id} belong to different sections.", record_ids=[clause.clause_id, parent.clause_id])
        elif clause.kind == "subclause":
            warning("subclause_without_parent", f"Subclause {clause.clause_id} has no parent clause.", record_ids=[clause.clause_id], element_ids=[clause.element_id])
        if clause.kind == "clause" and source.clause_number != clause.number:
            error("clause_number_mismatch", f"Clause {clause.clause_id} number disagrees with its element.", record_ids=[clause.clause_id], element_ids=[source.element_id])
        if clause.kind == "subclause" and source.subclause_marker != clause.number:
            error("subclause_marker_mismatch", f"Subclause {clause.clause_id} marker disagrees with its element.", record_ids=[clause.clause_id], element_ids=[source.element_id])
    # Sibling identity and sequence checks are semantic validation, not merely
    # foreign-key validation. Duplicate numbers/markers are contradictory and
    # therefore errors. Suspicious ordering/gaps require human review because
    # some source documents intentionally skip labels.
    sibling_groups: dict[tuple[str | None, str | None, str], list[ClauseRecord]] = {}
    for clause in structure.clauses:
        # Orphan subclauses are not proven siblings. Grouping every parent-less
        # marker in a section together creates false duplicate/sequence errors
        # for unrelated (a)/(b)/(i)/(ii) enumerations. Their missing parent is
        # already surfaced separately as subclause_without_parent.
        if clause.kind == "subclause" and clause.parent_clause_id is None:
            continue
        sibling_groups.setdefault((clause.section_id, clause.parent_clause_id, clause.kind), []).append(clause)

    def marker_ordinal(value: str) -> tuple[str, int] | None:
        token = value.strip().strip("()").strip()
        if token.isdigit():
            return ("numeric", int(token))
        if len(token) == 1 and token.isalpha():
            return ("alpha", ord(token.lower()) - ord("a") + 1)
        if re.fullmatch(r"[ivxlcdm]+", token.lower()) and len(token) > 1:
            roman = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
            total = 0
            previous = 0
            for char in reversed(token.lower()):
                current = roman[char]
                total += -current if current < previous else current
                previous = max(previous, current)
            return ("roman", total)
        return None

    def clause_sequence_value(value: str) -> tuple[str, tuple[int, ...]] | None:
        token = value.strip().rstrip(".")
        if not re.fullmatch(r"\d+(?:\.\d+)*", token):
            return None
        parts = tuple(int(part) for part in token.split("."))
        return (".".join(map(str, parts[:-1])), parts)

    for (_section_id, _parent_id, kind), siblings in sibling_groups.items():
        siblings.sort(key=lambda item: element_by_id[item.element_id].document_order if item.element_id in element_by_id else 10**9)
        number_to_records: dict[str, list[ClauseRecord]] = {}
        for sibling in siblings:
            number_to_records.setdefault(sibling.number.strip().lower(), []).append(sibling)
        for number, records in number_to_records.items():
            if not number or len(records) <= 1:
                continue

            if kind == "clause" and len(records) == 2:
                ordered_records = sorted(
                    records,
                    key=lambda record: element_by_id[record.element_id].document_order
                    if record.element_id in element_by_id else 10**9,
                )
                first_record, second_record = ordered_records
                first_element = element_by_id.get(first_record.element_id)
                second_element = element_by_id.get(second_record.element_id)
                page_by_number = {page.page_number: page for page in structure.pages}
                first_page = page_by_number.get(first_element.page_number) if first_element else None
                second_page = page_by_number.get(second_element.page_number) if second_element else None
                looks_like_page_break_continuation = bool(
                    first_element
                    and second_element
                    and first_page
                    and second_page
                    and second_element.page_number == first_element.page_number + 1
                    and first_element.bbox[3] >= first_page.height * 0.78
                    and second_element.bbox[1] <= second_page.height * 0.28
                )
                if looks_like_page_break_continuation:
                    warning(
                        "possible_cross_page_clause_continuation",
                        f"Clause number {first_record.number!r} is repeated across adjacent page-boundary elements and may be one cross-page clause rather than a true duplicate.",
                        record_ids=[record.clause_id for record in ordered_records],
                        element_ids=[record.element_id for record in ordered_records],
                        requires_review=True,
                    )
                    continue

            error(
                "duplicate_subclause_marker" if kind == "subclause" else "duplicate_clause_number",
                f"Sibling {kind} records repeat the number/marker {records[0].number!r}.",
                record_ids=[record.clause_id for record in records],
                element_ids=[record.element_id for record in records],
            )

        sequence: list[tuple[ClauseRecord, str, int]] = []
        for sibling in siblings:
            if kind == "subclause":
                parsed = marker_ordinal(sibling.number)
                if parsed is not None:
                    family, value = parsed
                    sequence.append((sibling, family, value))
            else:
                parsed_clause = clause_sequence_value(sibling.number)
                if parsed_clause is not None:
                    prefix, parts = parsed_clause
                    sequence.append((sibling, prefix, parts[-1]))
        for (left, left_family, left_value), (right, right_family, right_value) in zip(sequence, sequence[1:]):
            if left_family != right_family:
                continue
            if right_value <= left_value:
                warning(
                    "subclause_sibling_order" if kind == "subclause" else "clause_sibling_order",
                    f"Sibling {kind} sequence is not increasing: {left.number!r} → {right.number!r}.",
                    record_ids=[left.clause_id, right.clause_id],
                    element_ids=[left.element_id, right.element_id],
                )
            elif right_value - left_value > 1:
                warning(
                    "subclause_sibling_gap" if kind == "subclause" else "clause_sibling_gap",
                    f"Sibling {kind} sequence has a gap: {left.number!r} → {right.number!r}.",
                    record_ids=[left.clause_id, right.clause_id],
                    element_ids=[left.element_id, right.element_id],
                )

    cycle = _graph_cycle(set(clause_by_id), {cid: record.parent_clause_id for cid, record in clause_by_id.items()})
    if cycle:
        error("clause_cycle", "Clause parent hierarchy contains a cycle: " + " → ".join(cycle), record_ids=cycle)
    for element in elements:
        if element.type in {"clause", "subclause"} and element.clause_id:
            record = clause_by_id.get(element.clause_id)
            if record is None:
                error("element_clause_missing", f"Element {element.element_id} references missing clause {element.clause_id}.", element_ids=[element.element_id], record_ids=[element.clause_id])
            elif record.element_id != element.element_id:
                error("element_clause_owner_mismatch", f"Clause {element.clause_id} belongs to another element.", element_ids=[element.element_id, record.element_id], record_ids=[element.clause_id])

    definition_by_id = {entry.definition_id: entry for entry in structure.definitions}
    duplicate_definition_ids = _duplicate_values([entry.definition_id for entry in structure.definitions])
    if duplicate_definition_ids:
        error("duplicate_definition_id", "Duplicate definition IDs exist.", record_ids=duplicate_definition_ids)
    for entry in structure.definitions:
        if entry.section_id and entry.section_id not in section_by_id:
            error(
                "definition_section_missing",
                f"Definition {entry.definition_id} references missing section {entry.section_id}.",
                record_ids=[entry.definition_id, entry.section_id],
            )
        if entry.term_element_id:
            term = element_by_id.get(entry.term_element_id)
            if term is None:
                error("definition_term_missing", f"Definition {entry.definition_id} references missing term element.", record_ids=[entry.definition_id], element_ids=[entry.term_element_id])
            elif term.type != "definition_term" or term.definition_entry_id != entry.definition_id:
                error("definition_term_mismatch", f"Definition {entry.definition_id} term membership is inconsistent.", record_ids=[entry.definition_id], element_ids=[term.element_id])
            elif entry.section_id != term.section_id:
                error("definition_section_mismatch", f"Definition {entry.definition_id} and its term disagree on section membership.", record_ids=[entry.definition_id], element_ids=[term.element_id])
        if entry.source_table_element_id:
            # For normalized table-row definitions this ID is provenance: the
            # source table may intentionally disappear from the final canonical
            # element list after its rows are materialized as definition_term /
            # definition_text elements. Only validate section agreement when the
            # original table still exists as a live canonical table.
            source_table = element_by_id.get(entry.source_table_element_id)
            if source_table is not None and source_table.type == "table":
                if entry.section_id != source_table.section_id:
                    error("definition_table_section_mismatch", f"Definition {entry.definition_id} and its source table disagree on section membership.", record_ids=[entry.definition_id], element_ids=[source_table.element_id])
            elif entry.source_kind != "table_rows":
                error("definition_table_source_invalid", f"Definition {entry.definition_id} has an invalid source table element.", record_ids=[entry.definition_id], element_ids=[entry.source_table_element_id])
        for element_id in entry.definition_element_ids:
            member = element_by_id.get(element_id)
            if member is None:
                error("definition_text_missing", f"Definition {entry.definition_id} references missing definition text.", record_ids=[entry.definition_id], element_ids=[element_id])
            elif member.type != "definition_text" or member.definition_entry_id != entry.definition_id:
                error("definition_text_mismatch", f"Definition {entry.definition_id} text membership is inconsistent.", record_ids=[entry.definition_id], element_ids=[element_id])
            elif entry.section_id != member.section_id:
                error(
                    "definition_text_section_mismatch",
                    f"Definition text {member.element_id} disagrees with definition {entry.definition_id} on section membership.",
                    record_ids=[entry.definition_id],
                    element_ids=[member.element_id],
                )
        duplicate_members = _duplicate_values(entry.definition_element_ids)
        if duplicate_members:
            error(
                "definition_duplicate_member",
                f"Definition {entry.definition_id} repeats definition-text membership.",
                record_ids=[entry.definition_id],
                element_ids=duplicate_members,
            )
        record_elements: list[CanonicalElement] = []
        if entry.term_element_id and entry.term_element_id in element_by_id:
            record_elements.append(element_by_id[entry.term_element_id])
        if entry.source_table_element_id and entry.source_table_element_id in element_by_id:
            source_table = element_by_id[entry.source_table_element_id]
            if source_table.type == "table":
                record_elements.append(source_table)
        definition_members = [element_by_id[element_id] for element_id in entry.definition_element_ids if element_id in element_by_id]
        record_elements.extend(definition_members)
        if record_elements:
            expected_start = min(element.page_number for element in record_elements)
            expected_end = max(element.page_number for element in record_elements)
            if entry.start_page != expected_start or entry.end_page != expected_end:
                error(
                    "definition_page_range_mismatch",
                    f"Definition {entry.definition_id} page range {entry.start_page}–{entry.end_page} disagrees with member pages {expected_start}–{expected_end}.",
                    record_ids=[entry.definition_id],
                    element_ids=[element.element_id for element in record_elements],
                )
            if entry.spans_multiple_pages != (expected_end > expected_start):
                error(
                    "definition_span_flag_mismatch",
                    f"Definition {entry.definition_id} spans_multiple_pages does not match its member page range.",
                    record_ids=[entry.definition_id],
                )
        if definition_members:
            expected_order = [element.element_id for element in sorted(definition_members, key=lambda item: item.document_order)]
            if entry.definition_element_ids != expected_order:
                error(
                    "definition_member_order_mismatch",
                    f"Definition {entry.definition_id} definition_element_ids are not in document order.",
                    record_ids=[entry.definition_id],
                    element_ids=entry.definition_element_ids,
                )
            last_part = max(definition_members, key=lambda item: item.document_order)
            last_page = next((page for page in structure.pages if page.page_number == last_part.page_number), None)
            expected_continues = bool(
                last_page
                and last_part.bbox[3] >= last_page.height * 0.82
                and _text_looks_incomplete(last_part.text)
            )
            if entry.continues_to_next_page != expected_continues:
                error(
                    "definition_continuation_flag_mismatch",
                    f"Definition {entry.definition_id} continues_to_next_page disagrees with the final definition-text geometry/content.",
                    record_ids=[entry.definition_id],
                    element_ids=[last_part.element_id],
                )
    for element in elements:
        if element.type in {"definition_term", "definition_text"} and not element.definition_entry_id:
            error(
                "definition_member_unlinked",
                f"{element.type} element {element.element_id} is not assigned to a DefinitionEntry.",
                element_ids=[element.element_id],
            )
        elif element.type in {"definition_term", "definition_text"} and element.definition_entry_id not in definition_by_id:
            error("element_definition_missing", f"Element {element.element_id} references missing definition {element.definition_entry_id}.", element_ids=[element.element_id], record_ids=[element.definition_entry_id])

    table_by_id = {entry.logical_table_id: entry for entry in structure.tables}
    duplicate_table_ids = _duplicate_values([entry.logical_table_id for entry in structure.tables])
    if duplicate_table_ids:
        error("duplicate_table_id", "Duplicate logical table IDs exist.", record_ids=duplicate_table_ids)
    for entry in structure.tables:
        if entry.section_id and entry.section_id not in section_by_id:
            error(
                "table_section_missing",
                f"Logical table {entry.logical_table_id} references missing section {entry.section_id}.",
                record_ids=[entry.logical_table_id, entry.section_id],
            )
        seen_fragments: set[str] = set()
        resolved_fragments = [element_by_id[element_id] for element_id in entry.fragment_element_ids if element_id in element_by_id and element_by_id[element_id].type == "table"]
        expected_fragment_order = [fragment.element_id for fragment in sorted(resolved_fragments, key=lambda item: item.document_order)]
        if entry.fragment_element_ids != expected_fragment_order:
            error(
                "table_fragment_order_mismatch",
                f"Logical table {entry.logical_table_id} fragments are not stored in document order.",
                record_ids=[entry.logical_table_id],
                element_ids=entry.fragment_element_ids,
            )
        if resolved_fragments:
            expected_start = min(fragment.page_number for fragment in resolved_fragments)
            expected_end = max(fragment.page_number for fragment in resolved_fragments)
            if entry.start_page != expected_start or entry.end_page != expected_end:
                error(
                    "table_page_range_mismatch",
                    f"Logical table {entry.logical_table_id} page range {entry.start_page}–{entry.end_page} disagrees with fragment pages {expected_start}–{expected_end}.",
                    record_ids=[entry.logical_table_id],
                    element_ids=[fragment.element_id for fragment in resolved_fragments],
                )
            if entry.spans_multiple_pages != (expected_end > expected_start):
                error(
                    "table_span_flag_mismatch",
                    f"Logical table {entry.logical_table_id} spans_multiple_pages does not match its fragment page range.",
                    record_ids=[entry.logical_table_id],
                )
            fragment_col_counts = {fragment.table.col_count for fragment in resolved_fragments if fragment.table is not None}
            if len(fragment_col_counts) > 1 or (fragment_col_counts and entry.col_count not in fragment_col_counts):
                error(
                    "table_column_count_mismatch",
                    f"Logical table {entry.logical_table_id} column count disagrees with one or more fragments.",
                    record_ids=[entry.logical_table_id],
                    element_ids=[fragment.element_id for fragment in resolved_fragments],
                )
            expected_cells = [row for fragment in sorted(resolved_fragments, key=lambda item: item.document_order) for row in (fragment.table.cells if fragment.table else [])]
            if entry.row_count != len(entry.cells) or entry.cells != expected_cells:
                error(
                    "table_cells_mismatch",
                    f"Logical table {entry.logical_table_id} row_count/cells do not match its ordered fragments.",
                    record_ids=[entry.logical_table_id],
                    element_ids=[fragment.element_id for fragment in resolved_fragments],
                )
            for fragment in resolved_fragments:
                if fragment.table and (fragment.table.row_count != len(fragment.table.cells) or any(len(row) != fragment.table.col_count for row in fragment.table.cells)):
                    error(
                        "table_fragment_shape_mismatch",
                        f"Table fragment {fragment.element_id} row_count/col_count does not match its cells.",
                        record_ids=[entry.logical_table_id],
                        element_ids=[fragment.element_id],
                    )
        for fragment_index, element_id in enumerate(entry.fragment_element_ids):
            if element_id in seen_fragments:
                error("table_duplicate_fragment", f"Logical table {entry.logical_table_id} repeats fragment {element_id}.", record_ids=[entry.logical_table_id], element_ids=[element_id])
                continue
            seen_fragments.add(element_id)
            fragment = element_by_id.get(element_id)
            if fragment is None or fragment.type != "table":
                error("table_fragment_invalid", f"Logical table {entry.logical_table_id} contains a missing/non-table fragment.", record_ids=[entry.logical_table_id], element_ids=[element_id])
            elif fragment.logical_table_id != entry.logical_table_id:
                error("table_backref_mismatch", f"Table fragment {element_id} disagrees on logical_table_id.", record_ids=[entry.logical_table_id], element_ids=[element_id])
            elif fragment_index == 0 and fragment.section_id != entry.section_id:
                error(
                    "table_section_mismatch",
                    f"Logical table {entry.logical_table_id} and its first fragment disagree on section membership.",
                    record_ids=[entry.logical_table_id],
                    element_ids=[element_id],
                )
            elif fragment.section_id and entry.section_id and fragment.section_id != entry.section_id:
                warning(
                    "table_fragment_section_conflict",
                    f"Table fragment {element_id} is assigned to {fragment.section_id} while logical table {entry.logical_table_id} is assigned to {entry.section_id}.",
                    record_ids=[entry.logical_table_id, entry.section_id, fragment.section_id],
                    element_ids=[element_id],
                )
    for element in elements:
        if element.type == "table" and element.logical_table_id:
            entry = table_by_id.get(element.logical_table_id)
            if entry is None or element.element_id not in entry.fragment_element_ids:
                error("element_table_missing", f"Table element {element.element_id} has inconsistent logical-table membership.", element_ids=[element.element_id], record_ids=[element.logical_table_id])

    figure_by_id = {entry.figure_id: entry for entry in structure.figures}
    duplicate_figure_ids = _duplicate_values([entry.figure_id for entry in structure.figures])
    if duplicate_figure_ids:
        error("duplicate_figure_id", "Duplicate figure IDs exist.", record_ids=duplicate_figure_ids)
    for entry in structure.figures:
        figure = element_by_id.get(entry.element_id)
        if figure is None or figure.type != "figure" or figure.figure_id != entry.figure_id:
            error("figure_backref_mismatch", f"Figure {entry.figure_id} has inconsistent source membership.", record_ids=[entry.figure_id], element_ids=[entry.element_id])
        elif figure.section_id != entry.section_id:
            error(
                "figure_section_mismatch",
                f"Figure {entry.figure_id} and its source element disagree on section membership.",
                record_ids=[entry.figure_id],
                element_ids=[entry.element_id],
            )
        elif figure.page_number != entry.page_number:
            error(
                "figure_page_mismatch",
                f"Figure {entry.figure_id} page_number disagrees with its source element.",
                record_ids=[entry.figure_id],
                element_ids=[entry.element_id],
            )
        if entry.section_id and entry.section_id not in section_by_id:
            error(
                "figure_section_missing",
                f"Figure {entry.figure_id} references missing section {entry.section_id}.",
                record_ids=[entry.figure_id, entry.section_id],
            )
        membership_lists = [
            ("intro", entry.intro_element_ids),
            ("caption", entry.caption_element_ids),
            ("explanation", entry.explanation_element_ids),
            ("source", entry.source_element_ids),
        ]
        for membership_name, related_ids in membership_lists:
            duplicates = _duplicate_values(related_ids)
            if duplicates:
                error(
                    "figure_duplicate_membership",
                    f"Figure {entry.figure_id} repeats {membership_name} membership.",
                    record_ids=[entry.figure_id],
                    element_ids=duplicates,
                )
            for element_id in related_ids:
                if element_id not in ids:
                    error("figure_related_missing", f"Figure {entry.figure_id} references missing related element {element_id}.", record_ids=[entry.figure_id], element_ids=[element_id])
    for element in elements:
        if element.type == "figure" and element.figure_id and element.figure_id not in figure_by_id:
            error("element_figure_missing", f"Figure element {element.element_id} references missing figure record {element.figure_id}.", element_ids=[element.element_id], record_ids=[element.figure_id])

    appendix_by_id = {entry.appendix_id: entry for entry in structure.appendices}
    duplicate_appendix_ids = _duplicate_values([entry.appendix_id for entry in structure.appendices])
    if duplicate_appendix_ids:
        error("duplicate_appendix_id", "Duplicate appendix IDs exist.", record_ids=duplicate_appendix_ids)
    for entry in structure.appendices:
        label = element_by_id.get(entry.label_element_id)
        if label is None:
            error("appendix_label_missing", f"Appendix {entry.appendix_id} label element is missing.", record_ids=[entry.appendix_id], element_ids=[entry.label_element_id])
        elif label.appendix_id != entry.appendix_id:
            error(
                "appendix_label_backref_mismatch",
                f"Appendix {entry.appendix_id} label does not point back to the appendix record.",
                record_ids=[entry.appendix_id],
                element_ids=[entry.label_element_id],
            )
        appendix_members: list[CanonicalElement] = [label] if label is not None else []
        if entry.title_element_id:
            title = element_by_id.get(entry.title_element_id)
            if title is None:
                error("appendix_title_missing", f"Appendix {entry.appendix_id} title element is missing.", record_ids=[entry.appendix_id], element_ids=[entry.title_element_id])
            else:
                appendix_members.append(title)
                if title.appendix_id != entry.appendix_id:
                    error(
                        "appendix_title_backref_mismatch",
                        f"Appendix {entry.appendix_id} title does not point back to the appendix record.",
                        record_ids=[entry.appendix_id],
                        element_ids=[entry.title_element_id],
                    )
        if appendix_members:
            expected_start = min(element.page_number for element in appendix_members)
            expected_end = max(element.page_number for element in appendix_members)
            if entry.start_page != expected_start or entry.end_page != expected_end:
                error(
                    "appendix_page_range_mismatch",
                    f"Appendix {entry.appendix_id} page range disagrees with label/title element pages.",
                    record_ids=[entry.appendix_id],
                    element_ids=[element.element_id for element in appendix_members],
                )
    for element in elements:
        if element.appendix_id and element.appendix_id not in appendix_by_id:
            error("element_appendix_missing", f"Element {element.element_id} references missing appendix {element.appendix_id}.", element_ids=[element.element_id], record_ids=[element.appendix_id])

    relation_ids = [relation.relation_id for relation in structure.relationships]
    duplicate_relation_ids = _duplicate_values(relation_ids)
    if duplicate_relation_ids:
        error("duplicate_relation_id", "Duplicate relationship IDs exist.", record_ids=duplicate_relation_ids)
    seen_edges: set[tuple[str, str, str]] = set()
    clause_record_by_element = {record.element_id: record for record in structure.clauses}
    section_record_by_element = {record.element_id: record for record in structure.sections}
    appendix_label_by_element = {record.label_element_id: record for record in structure.appendices}
    figure_record_by_element = {record.element_id: record for record in structure.figures}
    figure_membership_attr = {
        "introduces": "intro_element_ids",
        "caption_of": "caption_element_ids",
        "explains": "explanation_element_ids",
        "source_for": "source_element_ids",
    }
    for relation in structure.relationships:
        if relation.source_element_id not in ids or relation.target_element_id not in ids:
            error("relationship_dangling", f"Relationship {relation.relation_id} has a missing endpoint.", record_ids=[relation.relation_id], element_ids=[relation.source_element_id, relation.target_element_id])
            continue
        if relation.source_element_id == relation.target_element_id:
            error("relationship_self", f"Relationship {relation.relation_id} links an element to itself.", record_ids=[relation.relation_id], element_ids=[relation.source_element_id])
        edge = (relation.type, relation.source_element_id, relation.target_element_id)
        if edge in seen_edges:
            error("relationship_duplicate_edge", f"Duplicate relationship edge {edge} exists.", record_ids=[relation.relation_id], element_ids=[relation.source_element_id, relation.target_element_id])
        seen_edges.add(edge)
        source = element_by_id[relation.source_element_id]
        target = element_by_id[relation.target_element_id]
        if relation.type == "continues":
            if source.document_order >= target.document_order:
                error("continues_not_forward", f"Relationship {relation.relation_id} does not point forward in document order.", record_ids=[relation.relation_id], element_ids=[source.element_id, target.element_id])
            if source.type != target.type:
                warning("continues_type_mismatch", f"Continuation {relation.relation_id} links different semantic types: {source.type} → {target.type}.", record_ids=[relation.relation_id], element_ids=[source.element_id, target.element_id])
            if source.type == "table" and target.type == "table":
                if source.logical_table_id and target.logical_table_id and source.logical_table_id != target.logical_table_id:
                    error(
                        "continues_table_mismatch",
                        f"Continuation {relation.relation_id} links fragments from different logical tables.",
                        record_ids=[relation.relation_id, source.logical_table_id, target.logical_table_id],
                        element_ids=[source.element_id, target.element_id],
                    )
                elif bool(source.logical_table_id) != bool(target.logical_table_id):
                    warning(
                        "continues_table_partial_membership",
                        f"Continuation {relation.relation_id} has logical-table membership on only one endpoint.",
                        record_ids=[relation.relation_id],
                        element_ids=[source.element_id, target.element_id],
                    )
            if source.type == "definition_text" and target.type == "definition_text":
                if source.definition_entry_id and target.definition_entry_id and source.definition_entry_id != target.definition_entry_id:
                    error(
                        "continues_definition_mismatch",
                        f"Continuation {relation.relation_id} links definition text from different definitions.",
                        record_ids=[relation.relation_id, source.definition_entry_id, target.definition_entry_id],
                        element_ids=[source.element_id, target.element_id],
                    )
                elif bool(source.definition_entry_id) != bool(target.definition_entry_id):
                    warning(
                        "continues_definition_partial_membership",
                        f"Continuation {relation.relation_id} has definition membership on only one endpoint.",
                        record_ids=[relation.relation_id],
                        element_ids=[source.element_id, target.element_id],
                    )
            if target.page_number - source.page_number > 1 and source.type in {"table", "definition_text"}:
                warning(
                    "continues_page_gap",
                    f"Continuation {relation.relation_id} skips one or more pages.",
                    record_ids=[relation.relation_id],
                    element_ids=[source.element_id, target.element_id],
                )
        elif relation.type == "parent_of":
            parent = clause_record_by_element.get(source.element_id)
            child = clause_record_by_element.get(target.element_id)
            if parent is None or child is None or child.parent_clause_id != parent.clause_id:
                error("parent_relation_mismatch", f"Relationship {relation.relation_id} disagrees with clause parent records.", record_ids=[relation.relation_id], element_ids=[source.element_id, target.element_id])
        elif relation.type in figure_membership_attr:
            figure_record = figure_record_by_element.get(target.element_id)
            membership_attr = figure_membership_attr[relation.type]
            if figure_record is None or source.element_id not in getattr(figure_record, membership_attr):
                error(
                    "figure_relation_mismatch",
                    f"Relationship {relation.relation_id} disagrees with FigureRecord membership.",
                    record_ids=[relation.relation_id] + ([figure_record.figure_id] if figure_record else []),
                    element_ids=[source.element_id, target.element_id],
                )
        elif relation.type == "belongs_to":
            clause = clause_record_by_element.get(source.element_id)
            section = section_record_by_element.get(target.element_id)
            if clause and section:
                if clause.section_id != section.section_id:
                    error("belongs_to_section_mismatch", f"Relationship {relation.relation_id} disagrees with clause section membership.", record_ids=[relation.relation_id, clause.clause_id, section.section_id], element_ids=[source.element_id, target.element_id])
            elif target.element_id in appendix_label_by_element:
                appendix = appendix_label_by_element[target.element_id]
                if appendix.title_element_id != source.element_id:
                    error("belongs_to_appendix_mismatch", f"Relationship {relation.relation_id} disagrees with appendix title membership.", record_ids=[relation.relation_id, appendix.appendix_id], element_ids=[source.element_id, target.element_id])
            else:
                warning("belongs_to_untyped", f"Relationship {relation.relation_id} is not backed by a known clause/section or appendix record.", record_ids=[relation.relation_id], element_ids=[source.element_id, target.element_id])

    edge_set = {(relation.type, relation.source_element_id, relation.target_element_id) for relation in structure.relationships}
    for clause in structure.clauses:
        if clause.kind == "clause" and clause.section_id and clause.section_id in section_by_id:
            expected = ("belongs_to", clause.element_id, section_by_id[clause.section_id].element_id)
            if expected not in edge_set:
                error(
                    "clause_section_relation_missing",
                    f"Clause {clause.clause_id} section membership is missing its belongs_to relationship.",
                    record_ids=[clause.clause_id, clause.section_id],
                    element_ids=[expected[1], expected[2]],
                )
        if clause.parent_clause_id and clause.parent_clause_id in clause_by_id:
            parent = clause_by_id[clause.parent_clause_id]
            expected = ("parent_of", parent.element_id, clause.element_id)
            if expected not in edge_set:
                error(
                    "clause_parent_relation_missing",
                    f"Clause {clause.clause_id} parent membership is missing its parent_of relationship.",
                    record_ids=[clause.clause_id, parent.clause_id],
                    element_ids=[parent.element_id, clause.element_id],
                )

    for table in structure.tables:
        fragments = [element_by_id[element_id] for element_id in table.fragment_element_ids if element_id in element_by_id]
        fragments.sort(key=lambda element: element.document_order)
        for left, right in zip(fragments, fragments[1:]):
            if left.page_number == right.page_number:
                continue
            expected = ("continues", left.element_id, right.element_id)
            if expected not in edge_set:
                error(
                    "table_continuation_relation_missing",
                    f"Logical table {table.logical_table_id} is missing a cross-page continues relationship.",
                    record_ids=[table.logical_table_id],
                    element_ids=[left.element_id, right.element_id],
                )

    for definition in structure.definitions:
        members = [element_by_id[element_id] for element_id in definition.definition_element_ids if element_id in element_by_id]
        members = [element for element in members if element.type == "definition_text"]
        members.sort(key=lambda element: element.document_order)
        for left, right in zip(members, members[1:]):
            if left.page_number == right.page_number:
                continue
            expected = ("continues", left.element_id, right.element_id)
            if expected not in edge_set:
                error(
                    "definition_continuation_relation_missing",
                    f"Definition {definition.definition_id} is missing a cross-page continues relationship.",
                    record_ids=[definition.definition_id],
                    element_ids=[left.element_id, right.element_id],
                )

    for figure in structure.figures:
        expected = [
            *(('introduces', source, figure.element_id) for source in figure.intro_element_ids),
            *(('caption_of', source, figure.element_id) for source in figure.caption_element_ids),
            *(('explains', source, figure.element_id) for source in figure.explanation_element_ids),
            *(('source_for', source, figure.element_id) for source in figure.source_element_ids),
        ]
        for relation_type, source, target in expected:
            if (relation_type, source, target) not in edge_set:
                error(
                    "figure_relation_missing",
                    f"Figure {figure.figure_id} membership is missing its {relation_type} relationship.",
                    record_ids=[figure.figure_id],
                    element_ids=[source, target],
                )
    for appendix in structure.appendices:
        if appendix.title_element_id and ("belongs_to", appendix.title_element_id, appendix.label_element_id) not in edge_set:
            error(
                "appendix_relation_missing",
                f"Appendix {appendix.appendix_id} title membership is missing its belongs_to relationship.",
                record_ids=[appendix.appendix_id],
                element_ids=[appendix.title_element_id, appendix.label_element_id],
            )

    counts = {
        "elements": len(elements),
        "sections": len(structure.sections),
        "clauses": len(structure.clauses),
        "definitions": len(structure.definitions),
        "tables": len(structure.tables),
        "figures": len(structure.figures),
        "appendices": len(structure.appendices),
        "relationships": len(structure.relationships),
        "errors": len(errors),
        "warnings": len(warnings),
    }
    semantic_status = "blocked" if errors else ("review_required" if any(issue.requires_review for issue in warnings) else "clear")
    return RelationshipIntegrityReport(
        status="fail" if errors else "pass",
        semantic_status=semantic_status,
        errors=errors,
        warnings=warnings,
        counts=counts,
    )


def _review_state_for_report(
    report: RelationshipIntegrityReport,
    persisted: RelationshipReviewState,
) -> RelationshipReviewState:
    """Compatibility review metadata for the simplified Stage 4.5 gate.

    Stage 5 readiness now depends only on blocking structural-integrity errors.
    Semantic warnings remain diagnostics and never require explicit approval.
    The legacy review fields are preserved so older saved artifacts and API
    clients can still be loaded without a migration.
    """
    required_ids = {issue.issue_id for issue in report.warnings if issue.requires_review}
    approved_ids = sorted(required_ids.intersection(persisted.approved_issue_ids))
    if report.status == "fail":
        return RelationshipReviewState(
            status="blocked",
            approved_issue_ids=approved_ids,
            pending_issue_ids=[],
            approved_at=None,
            note=persisted.note,
            stage5_eligible=False,
        )
    pending_ids = sorted(required_ids.difference(approved_ids))
    if persisted.status == "approved" and not pending_ids:
        return RelationshipReviewState(
            status="approved",
            approved_issue_ids=approved_ids,
            pending_issue_ids=[],
            approved_at=persisted.approved_at,
            note=persisted.note,
            stage5_eligible=True,
        )
    if required_ids:
        return RelationshipReviewState(
            status="needs_review",
            approved_issue_ids=approved_ids,
            pending_issue_ids=pending_ids,
            approved_at=None,
            note=persisted.note,
            stage5_eligible=True,
        )
    return RelationshipReviewState(
        status="not_reviewed",
        approved_issue_ids=[],
        pending_issue_ids=[],
        approved_at=None,
        note=persisted.note,
        stage5_eligible=True,
    )


def _reconcile_records(structure: StructuredDocument, warnings: list[str]) -> None:
    ids = _existing_element_ids(structure)
    element_by_id = {element.element_id: element for page in structure.pages for element in page.elements}
    type_by_id = {element_id: element.type for element_id, element in element_by_id.items()}

    if (
        structure.outline_root_element_id not in ids
        or type_by_id.get(structure.outline_root_element_id) != "title"
    ):
        structure.outline_root_element_id = None
    structure.metadata_element_ids = [
        element_id for element_id in structure.metadata_element_ids
        if element_id in ids and type_by_id.get(element_id) == "document_metadata"
    ]

    original_sections = len(structure.sections)
    structure.sections = [
        section for section in structure.sections
        if section.element_id in ids and type_by_id.get(section.element_id) == "section_header"
    ]
    if len(structure.sections) != original_sections:
        warnings.append("One or more automatic section records were removed because their source headers were manually changed or deleted.")

    valid_section_ids = {section.section_id for section in structure.sections}
    for section in structure.sections:
        section.content_element_ids = [element_id for element_id in section.content_element_ids if element_id in ids]
        if section.parent_section_id not in valid_section_ids:
            section.parent_section_id = None
        source = element_by_id.get(section.element_id)
        if source is not None:
            section.page_number = source.page_number
            section.title = source.text.strip() or section.title
            source.section_id = section.section_id
            source.heading_level = section.level
            source.heading_level_source = section.level_source
    for element in element_by_id.values():
        if element.section_id not in valid_section_ids:
            element.section_id = None

    structure.definitions = [
        entry for entry in structure.definitions
        if (
            (entry.term_element_id is None or entry.term_element_id in ids)
            and (
                entry.source_table_element_id is None
                or entry.source_kind == "table_rows"
                or entry.source_table_element_id in ids
            )
            and all(element_id in ids for element_id in entry.definition_element_ids)
        )
    ]
    original_clauses = len(structure.clauses)
    structure.clauses = [
        entry for entry in structure.clauses
        if entry.element_id in ids and type_by_id.get(entry.element_id) == entry.kind
    ]
    valid_clause_ids = {entry.clause_id for entry in structure.clauses}
    for entry in structure.clauses:
        element = element_by_id[entry.element_id]
        entry.page_number = element.page_number
        entry.section_id = element.section_id
        if entry.parent_clause_id not in valid_clause_ids:
            entry.parent_clause_id = None
        element.clause_id = entry.clause_id
        element.parent_clause_id = entry.parent_clause_id
        if entry.kind == "clause":
            element.clause_number = entry.number
            element.subclause_marker = None
        else:
            element.clause_number = None
            element.subclause_marker = entry.number
    if len(structure.clauses) != original_clauses:
        warnings.append("One or more automatic clause records were removed because their source elements were manually changed or deleted.")
    original_appendices = len(structure.appendices)
    structure.appendices = [
        entry for entry in structure.appendices
        if (
            entry.label_element_id in ids
            and type_by_id.get(entry.label_element_id) == "section_header"
            and (
                entry.title_element_id is None
                or (
                    entry.title_element_id in ids
                    and type_by_id.get(entry.title_element_id) in {"section_header", "subtitle", "title"}
                )
            )
        )
    ]
    valid_appendix_ids = {entry.appendix_id for entry in structure.appendices}
    for entry in structure.appendices:
        appendix_elements = [element_by_id[entry.label_element_id]]
        entry.label = " ".join(element_by_id[entry.label_element_id].text.split()) or entry.label
        label_element = element_by_id[entry.label_element_id]
        label_element.appendix_id = entry.appendix_id
        if entry.title_element_id:
            title_element = element_by_id[entry.title_element_id]
            title_element.appendix_id = entry.appendix_id
            appendix_elements.append(title_element)
            entry.title = title_element.text.strip() or entry.title
        entry.start_page = min(element.page_number for element in appendix_elements)
        entry.end_page = max(element.page_number for element in appendix_elements)
    for element in element_by_id.values():
        if element.appendix_id not in valid_appendix_ids:
            element.appendix_id = None
    if len(structure.appendices) != original_appendices:
        warnings.append("One or more automatic appendix records were removed because their label/title elements were manually changed or deleted.")

    rebuilt_tables = []
    for entry in structure.tables:
        fragments = [element_by_id.get(element_id) for element_id in entry.fragment_element_ids]
        if not fragments or any(fragment is None or fragment.type != "table" or fragment.table is None for fragment in fragments):
            warnings.append(f"Logical table {entry.logical_table_id} was removed because a fragment was manually changed or deleted.")
            continue
        table_fragments = [fragment for fragment in fragments if fragment is not None and fragment.table is not None]
        table_fragments.sort(key=lambda fragment: fragment.document_order)
        column_counts = {fragment.table.col_count for fragment in table_fragments}
        if len(column_counts) != 1:
            warnings.append(f"Logical table {entry.logical_table_id} was removed because corrected fragments no longer share a column count.")
            continue
        entry.fragment_element_ids = [fragment.element_id for fragment in table_fragments]
        entry.start_page = min(fragment.page_number for fragment in table_fragments)
        entry.end_page = max(fragment.page_number for fragment in table_fragments)
        entry.spans_multiple_pages = entry.start_page != entry.end_page
        entry.col_count = next(iter(column_counts))
        entry.cells = [row for fragment in table_fragments for row in fragment.table.cells]
        entry.row_count = len(entry.cells)
        entry.section_id = table_fragments[0].section_id
        rebuilt_tables.append(entry)
    structure.tables = rebuilt_tables
    valid_table_ids = {entry.logical_table_id for entry in structure.tables}
    for element in element_by_id.values():
        if element.logical_table_id and element.logical_table_id not in valid_table_ids:
            element.logical_table_id = None

    structure.figures = [entry for entry in structure.figures if entry.element_id in ids and type_by_id.get(entry.element_id) == "figure"]
    valid_figure_ids = {entry.figure_id for entry in structure.figures}
    for entry in structure.figures:
        element = element_by_id[entry.element_id]
        element.figure_id = entry.figure_id
        entry.page_number = element.page_number
        entry.section_id = element.section_id
        def keep_related(element_ids: list[str], allowed_after_manual_change: set[str]) -> list[str]:
            kept_ids: list[str] = []
            for element_id in dict.fromkeys(element_ids):
                related = element_by_id.get(element_id)
                if related is None:
                    continue
                if related.role_source.startswith("manual_") and related.type not in allowed_after_manual_change:
                    continue
                kept_ids.append(element_id)
            return kept_ids

        entry.intro_element_ids = keep_related(
            entry.intro_element_ids, {"paragraph", "list_item", "clause", "subclause"}
        )
        entry.caption_element_ids = keep_related(entry.caption_element_ids, {"caption"})
        entry.explanation_element_ids = keep_related(entry.explanation_element_ids, {"paragraph", "list_item"})
        entry.source_element_ids = keep_related(
            entry.source_element_ids, {"paragraph", "list_item", "caption", "footnote"}
        )
    for element in element_by_id.values():
        if element.figure_id and element.figure_id not in valid_figure_ids:
            element.figure_id = None
    structure.relationships = [
        relation for relation in structure.relationships
        if relation.source_element_id in ids and relation.target_element_id in ids
    ]


def _rebuild_layout_definition_records(structure: StructuredDocument) -> None:
    """Rebuild geometry-based definitions after manual membership edits.

    Stage 4.5 can relabel, split, merge, draw, suppress, and manually link
    definition terms/text. The automatic ``DefinitionEntry`` objects therefore
    cannot be treated as immutable snapshots. Rebuild layout-column entries
    from the corrected element ``definition_entry_id`` values while preserving
    still-valid table-row definitions, which are represented directly by their
    source table rather than by child definition elements.
    """
    element_by_id = {
        element.element_id: element
        for page in structure.pages
        for element in page.elements
    }
    table_definitions = [
        entry
        for entry in structure.definitions
        if (
            entry.source_kind == "table_rows"
            and entry.source_table_element_id is not None
            and entry.source_table_element_id in element_by_id
            and element_by_id[entry.source_table_element_id].type == "table"
        )
    ]
    for entry in table_definitions:
        if entry.source_table_element_id:
            source_table = element_by_id.get(entry.source_table_element_id)
            if source_table is not None:
                entry.section_id = source_table.section_id
    all_elements = [element for page in structure.pages for element in page.elements]
    layout_definitions = _build_definition_entries(all_elements, structure.pages)
    # A DefinitionEntry owns the semantic section context for its term and all
    # definition-text members. This repairs manually drawn/linked text that had
    # no section_id and prevents sibling definition text from drifting across
    # sections after correction.
    for entry in layout_definitions:
        if entry.term_element_id and entry.term_element_id in element_by_id:
            section_id = element_by_id[entry.term_element_id].section_id
            entry.section_id = section_id
            for element_id in entry.definition_element_ids:
                member = element_by_id.get(element_id)
                if member is not None:
                    member.section_id = section_id
    valid_layout_definition_ids = {entry.definition_id for entry in layout_definitions}
    for element in all_elements:
        if (
            element.type in {"definition_term", "definition_text"}
            and element.definition_entry_id
            and element.definition_entry_id not in valid_layout_definition_ids
        ):
            element.definition_entry_id = None

    order_by_id = {element.element_id: element.document_order for element in all_elements}

    def sort_key(entry):
        if entry.term_element_id and entry.term_element_id in order_by_id:
            return (order_by_id[entry.term_element_id], 0)
        if entry.source_table_element_id and entry.source_table_element_id in order_by_id:
            return (order_by_id[entry.source_table_element_id], 1)
        return (10**9, 2)

    structure.definitions = sorted([*layout_definitions, *table_definitions], key=sort_key)


def resolve_structure(
    *,
    automatic: StructuredDocument,
    extraction: DocumentExtraction,
    corrections: CorrectionArtifact,
) -> ResolvedStructureArtifact:
    if automatic.document_id != corrections.document_id:
        raise InvalidCorrectionError("Correction artifact belongs to a different document.")
    if automatic.source_sha256 != corrections.source_sha256:
        raise StaleCorrectionError("Corrections are stale because the source document changed.")
    if automatic.structured_at != corrections.base_structured_at:
        raise StaleCorrectionError("Corrections are stale because Stage 4 was re-run. Reset corrections and review the new automatic structure.")

    # Validate the automatic baseline after deterministic compatibility
    # normalization only. Stage 4.5 does not infer or rewrite missing legal
    # hierarchy parents; the stored Stage-4 JSON remains immutable.
    baseline_view = deepcopy(automatic)
    _normalize_legacy_definition_provenance(baseline_view)
    _rebuild_derived_hierarchy_relations(baseline_view)
    baseline_integrity = _relationship_integrity_report(baseline_view)

    resolved = deepcopy(automatic)
    warnings: list[str] = []
    _normalize_legacy_definition_provenance(resolved)
    _refine_recovered_definition_provenance(resolved, extraction)

    operation_ids: set[str] = set()
    for operation in corrections.operations:
        if operation.operation_id in operation_ids:
            raise InvalidCorrectionError(f"Duplicate correction operation_id: {operation.operation_id}")
        operation_ids.add(operation.operation_id)

    operations_by_page: dict[int, list[CorrectionOperation]] = {}
    for operation in corrections.operations:
        if (
            operation.operation not in RELATIONSHIP_OPERATIONS
            and operation.operation not in DEFINITION_MEMBERSHIP_OPERATIONS
            and operation.operation not in STRUCTURAL_OPERATIONS
        ):
            operations_by_page.setdefault(operation.page_number, []).append(operation)

    for page in resolved.pages:
        page_operations = operations_by_page.get(page.page_number, [])
        for operation in page_operations:
            _apply_operation(
                page.elements,
                operation,
                page_number=page.page_number,
                width=page.width,
                height=page.height,
                extraction=extraction,
            )
        if any(operation.operation in GEOMETRY_OPERATIONS for operation in page_operations):
            touched_ids: set[str] = set()
            for operation in page_operations:
                if operation.operation == "move_resize":
                    touched_ids.update(operation.source_element_ids)
                elif operation.operation in {"split", "merge", "draw", "span_rebuild"}:
                    touched_ids.update(spec.element_id for spec in operation.result_elements)
            _reconcile_page_reading_order(page.elements, touched_ids)

    # Operations that point to non-existent pages should fail instead of being silently ignored.
    valid_pages = {page.page_number for page in resolved.pages}
    referenced_operation_pages = {operation.page_number for operation in corrections.operations}
    referenced_operation_pages.update(
        operation.target_page_number
        for operation in corrections.operations
        if operation.target_page_number is not None
    )
    invalid_pages = sorted(referenced_operation_pages - valid_pages)
    if invalid_pages:
        raise InvalidCorrectionError(f"Correction operations reference missing pages: {invalid_pages}")

    _assert_global_unique_element_ids(resolved)

    document_order = 0
    all_elements: list[CanonicalElement] = []
    for page in resolved.pages:
        for reading_order, element in enumerate(page.elements):
            element.page_number = page.page_number
            element.reading_order = reading_order
            element.document_order = document_order
            document_order += 1
            all_elements.append(element)
        page.body_text = "\n\n".join(
            text for text in (_element_body_text(element) for element in page.elements) if text
        )

    _apply_structural_operations(resolved, corrections.operations)
    _validate_structural_intents_before_reconcile(resolved, corrections.operations)
    for page in resolved.pages:
        page.body_text = "\n\n".join(
            text for text in (_element_body_text(element) for element in page.elements) if text
        )
    resolved.body_text = "\n\n".join(page.body_text for page in resolved.pages if page.body_text)
    # Manual definition membership is explicit in Stage 4.5.8.16.
    # Relabelling/drawing a definition_text never guesses its DefinitionEntry;
    # the reviewer selects the owning definition and the resolver derives only
    # deterministic back-references such as section membership.
    _apply_definition_membership_operations(resolved, corrections.operations)
    _reconcile_records(resolved, warnings)

    # Keep compatibility normalization deterministic.  Stage 4.5 no longer
    # guesses missing legal hierarchy parents; unknown parents stay unknown.
    _normalize_legacy_definition_provenance(resolved)
    _rebuild_layout_definition_records(resolved)
    _rebuild_section_content_membership(resolved)
    _rebuild_record_backed_continuation_relations(resolved)
    _rebuild_derived_hierarchy_relations(resolved)
    _rebuild_figure_relations(resolved)
    _apply_relationship_operations(resolved, corrections.operations)
    _assert_global_unique_element_ids(resolved)

    integrity = _relationship_integrity_report(resolved)

    counts = Counter(element.type for element in all_elements)
    resolved.summary.element_count = len(all_elements)
    resolved.summary.body_text_char_count = len(resolved.body_text)
    resolved.summary.section_count = len(resolved.sections)
    resolved.summary.definition_count = len(resolved.definitions)
    resolved.summary.clause_count = len(resolved.clauses)
    resolved.summary.appendix_count = len(resolved.appendices)
    resolved.summary.logical_table_count = len(resolved.tables)
    resolved.summary.figure_count = len(resolved.figures)
    resolved.summary.relation_count = len(resolved.relationships)
    resolved.summary.element_counts = dict(sorted(counts.items()))
    resolved.warnings = list(dict.fromkeys([*resolved.warnings, *warnings]))

    # The base automatic structured_at remains unchanged by design. The envelope
    # records resolved_at separately so stale correction detection stays reliable.
    return ResolvedStructureArtifact(
        document_id=automatic.document_id,
        source_sha256=automatic.source_sha256,
        base_structured_at=automatic.structured_at,
        correction_count=len(corrections.operations),
        resolved_at=datetime.now(timezone.utc),
        structure=resolved,
        baseline_integrity=baseline_integrity,
        integrity=integrity,
        review=_review_state_for_report(integrity, corrections.relationship_review),
        warnings=warnings,
    )
