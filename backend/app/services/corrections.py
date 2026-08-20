from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone

from app.schemas import (
    CanonicalElement,
    CanonicalSourceTrace,
    CorrectionArtifact,
    CorrectionElementSpec,
    CorrectionOperation,
    CorrectionRelationshipSpec,
    DocumentExtraction,
    ResolvedStructureArtifact,
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


class StaleCorrectionError(ValueError):
    pass


class InvalidCorrectionError(ValueError):
    pass


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

    x0, x1 = sorted((max(0.0, min(width, x0)), max(0.0, min(width, x1))))
    y0, y1 = sorted((max(0.0, min(height, y0)), max(0.0, min(height, y1))))
    if x1 - x0 < 1.0 or y1 - y0 < 1.0:
        raise InvalidCorrectionError("Bounding boxes must have a width and height of at least 1 PDF point.")
    return [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)]


def _raw_page(extraction: DocumentExtraction, page_number: int):
    return next((page for page in extraction.pages if page.page_number == page_number), None)


def _source_trace_for_bbox(extraction: DocumentExtraction, page_number: int, bbox: list[float], source_class: str) -> CanonicalSourceTrace:
    raw_page = _raw_page(extraction, page_number)
    if raw_page is None:
        return CanonicalSourceTrace(
            layout_box_index=-1,
            layout_box_class=source_class,
            stage3_block_ids=[],
            stage3_table_ids=[],
        )

    block_ids: list[str] = []
    for block in raw_page.blocks:
        block_area = max(_area(block.bbox), 1.0)
        overlap = _intersection_area(block.bbox, bbox) / block_area
        if overlap >= 0.2 or _center_inside(block.bbox, bbox):
            block_ids.append(block.block_id)

    table_ids: list[str] = []
    for table in raw_page.tables:
        table_area = max(_area(table.bbox), 1.0)
        overlap = _intersection_area(table.bbox, bbox) / table_area
        if overlap >= 0.2 or _center_inside(table.bbox, bbox):
            table_ids.append(table.table_id)

    return CanonicalSourceTrace(
        layout_box_index=-1,
        layout_box_class=source_class,
        stage3_block_ids=block_ids,
        stage3_table_ids=table_ids,
    )


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
                span_area = max(_area(span.bbox), 1.0)
                overlap = _intersection_area(span.bbox, bbox) / span_area
                if overlap < 0.35 and not _center_inside(span.bbox, bbox):
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


def _element_body_text(element: CanonicalElement) -> str:
    if element.type not in CONTENT_TYPES:
        return ""
    if element.type == "table" and element.table and element.table.markdown:
        return element.table.markdown.strip()
    return element.text.strip()


def _find_index(elements: list[CanonicalElement], element_id: str) -> int:
    return next((index for index, element in enumerate(elements) if element.element_id == element_id), -1)


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
    bbox = _normalize_bbox(spec.bbox, width, height)
    text = _text_from_bbox(extraction, page_number, bbox)

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
        element.source = _source_trace_for_bbox(extraction, page_number, bbox, role_source)
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
        source=_source_trace_for_bbox(extraction, page_number, bbox, role_source),
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
    if operation.operation in RELATIONSHIP_OPERATIONS:
        return

    if operation.operation == "relabel":
        if len(operation.source_element_ids) != 1 or operation.new_type is None:
            raise InvalidCorrectionError("Relabel requires one source element and a new_type.")
        index = _find_index(elements, operation.source_element_ids[0])
        if index < 0:
            raise InvalidCorrectionError(f"Relabel source not found: {operation.source_element_ids[0]}")
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
        insert_at = min(indices)
        template = source_elements[0]
        result = _spec_to_element(
            spec=operation.result_elements[0],
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

    if operation.operation == "draw":
        if operation.source_element_ids or len(operation.result_elements) != 1:
            raise InvalidCorrectionError("Draw requires no source and exactly one result element.")
        spec = operation.result_elements[0]
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
    )


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


def _existing_element_ids(structure: StructuredDocument) -> set[str]:
    return {element.element_id for page in structure.pages for element in page.elements}


def _reconcile_records(structure: StructuredDocument, warnings: list[str]) -> None:
    ids = _existing_element_ids(structure)
    type_by_id = {element.element_id: element.type for page in structure.pages for element in page.elements}

    original_sections = len(structure.sections)
    structure.sections = [
        section for section in structure.sections
        if section.element_id in ids and type_by_id.get(section.element_id) == "section_header"
    ]
    if len(structure.sections) != original_sections:
        warnings.append("One or more automatic section records were removed because their source headers were manually changed or deleted.")

    structure.definitions = [
        entry for entry in structure.definitions
        if (
            (entry.term_element_id is None or entry.term_element_id in ids)
            and (entry.source_table_element_id is None or entry.source_table_element_id in ids)
            and all(element_id in ids for element_id in entry.definition_element_ids)
        )
    ]
    structure.clauses = [entry for entry in structure.clauses if entry.element_id in ids]
    structure.appendices = [
        entry for entry in structure.appendices
        if entry.label_element_id in ids and (entry.title_element_id is None or entry.title_element_id in ids)
    ]
    structure.tables = [entry for entry in structure.tables if all(element_id in ids for element_id in entry.fragment_element_ids)]
    structure.figures = [entry for entry in structure.figures if entry.element_id in ids and type_by_id.get(entry.element_id) == "figure"]
    structure.relationships = [
        relation for relation in structure.relationships
        if relation.source_element_id in ids and relation.target_element_id in ids
    ]


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

    resolved = deepcopy(automatic)
    warnings: list[str] = []

    operation_ids: set[str] = set()
    for operation in corrections.operations:
        if operation.operation_id in operation_ids:
            raise InvalidCorrectionError(f"Duplicate correction operation_id: {operation.operation_id}")
        operation_ids.add(operation.operation_id)

    operations_by_page: dict[int, list[CorrectionOperation]] = {}
    for operation in corrections.operations:
        if operation.operation not in RELATIONSHIP_OPERATIONS:
            operations_by_page.setdefault(operation.page_number, []).append(operation)

    for page in resolved.pages:
        for operation in operations_by_page.get(page.page_number, []):
            _apply_operation(
                page.elements,
                operation,
                page_number=page.page_number,
                width=page.width,
                height=page.height,
                extraction=extraction,
            )

    # Operations that point to non-existent pages should fail instead of being silently ignored.
    valid_pages = {page.page_number for page in resolved.pages}
    referenced_operation_pages = {operation.page_number for operation in corrections.operations}
    invalid_pages = sorted(referenced_operation_pages - valid_pages)
    if invalid_pages:
        raise InvalidCorrectionError(f"Correction operations reference missing pages: {invalid_pages}")

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

    resolved.body_text = "\n\n".join(page.body_text for page in resolved.pages if page.body_text)
    _apply_relationship_operations(resolved, corrections.operations)
    _reconcile_records(resolved, warnings)

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
        warnings=warnings,
    )
