from __future__ import annotations

from collections.abc import Iterable, Mapping
import logging
import re
from typing import Any

from app.schemas import RetrievalChunk, StructuredDocument, VisualReference
from app.services.storage import read_chunking_artifact, read_resolved_structure, read_structure


logger = logging.getLogger(__name__)


class VisualAssetNotFoundError(LookupError):
    pass


_EXPLICIT_VISUAL_REFERENCE_RE = re.compile(
    r"\b(?:illustrat(?:ed|ion)|figure|diagram|chart|flowchart|image|overview|shown|set\s+out|depicted|presented)\b",
    re.IGNORECASE,
)
_SUMMARY_REFERENCE_RE = re.compile(
    r"\b(?:above|overview|process|steps?|workflow|breakdown|structure|following)\b",
    re.IGNORECASE,
)


def _as_dict(value: RetrievalChunk | Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return dict(value.model_dump())
    raise TypeError(f"Unsupported chunk payload: {type(value)!r}")


def _ordered_text(element_by_id: dict[str, Any], element_ids: Iterable[str]) -> str:
    rows = [element_by_id[element_id] for element_id in element_ids if element_id in element_by_id]
    rows.sort(key=lambda element: int(element.document_order))
    return " ".join(" ".join(element.text.split()) for element in rows if element.text.strip()).strip()


def _bbox_area(bbox: list[float]) -> float:
    if len(bbox) != 4:
        return 0.0
    return max(0.0, float(bbox[2]) - float(bbox[0])) * max(0.0, float(bbox[3]) - float(bbox[1]))


def _figure_is_displayable(figure: Any, element_by_id: dict[str, Any]) -> bool:
    """Reject obvious decorative/front-page picture fragments without hiding real figures.

    The current SC corpus contains several page-1 picture regions emitted by the
    layout engine for cover artwork/text fragments. They have no canonical section
    or figure label. Real information-bearing figures are section-scoped or carry a
    caption/introduction, so this conservative rule removes the known false positives
    without requiring image classification.
    """

    element = element_by_id.get(figure.element_id)
    if element is None or _bbox_area(list(element.bbox)) <= 0:
        return False
    return bool(
        figure.section_id
        or figure.caption_element_ids
        or figure.intro_element_ids
    )


def _figure_label(figure: Any, element_by_id: dict[str, Any]) -> str:
    caption_like_ids = [
        element_id
        for element_id in [*figure.caption_element_ids, *figure.intro_element_ids]
        if element_id in element_by_id and element_by_id[element_id].type == "caption"
    ]
    caption_like = _ordered_text(element_by_id, caption_like_ids)
    if caption_like:
        return caption_like[:220]
    caption = _ordered_text(element_by_id, figure.caption_element_ids)
    if caption:
        return caption[:220]
    intro = _ordered_text(element_by_id, figure.intro_element_ids)
    if intro and len(intro) <= 220:
        return intro
    return "Figure / image"


def _table_label(table: Any, element_by_id: dict[str, Any]) -> str:
    fragments = [element_by_id[element_id] for element_id in table.fragment_element_ids if element_id in element_by_id]
    if not fragments:
        return "Table"
    first = min(fragments, key=lambda element: int(element.document_order))
    page_elements = [element for element in element_by_id.values() if int(element.page_number) == int(first.page_number)]
    captions = []
    for candidate in page_elements:
        if candidate.type != "caption" or int(candidate.document_order) >= int(first.document_order):
            continue
        gap = float(first.bbox[1]) - float(candidate.bbox[3])
        if -3 <= gap <= 55:
            captions.append(candidate)
    if captions:
        caption = max(captions, key=lambda element: int(element.document_order))
        text = " ".join(caption.text.split()).strip()
        if text:
            return text[:220]
    return "Table"


def _page_gap(chunk_pages: Iterable[int], page_number: int) -> int:
    pages = [int(page) for page in chunk_pages]
    if not pages:
        return 0
    return min(abs(page - int(page_number)) for page in pages)


def _chunk_metadata(structure: StructuredDocument, chunks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    element_by_id = {
        element.element_id: element
        for page in structure.pages
        for element in page.elements
    }
    output: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        source_ids = [str(value) for value in chunk.get("source_element_ids", []) if str(value) in element_by_id]
        elements = [element_by_id[element_id] for element_id in source_ids]
        section_ids = {str(element.section_id) for element in elements if element.section_id}
        orders = [int(element.document_order) for element in elements]
        output[str(chunk["chunk_id"])] = {
            "chunk": chunk,
            "source_ids": set(source_ids),
            "section_ids": section_ids,
            "min_order": min(orders) if orders else None,
            "max_order": max(orders) if orders else None,
            "pages": [int(value) for value in chunk.get("pages", [])],
        }
    return output


def _append_ref(target: list[VisualReference], ref: VisualReference) -> None:
    key = (ref.asset_type, ref.visual_id, int(ref.page_number))
    for index, existing in enumerate(target):
        existing_key = (existing.asset_type, existing.visual_id, int(existing.page_number))
        if existing_key != key:
            continue
        if ref.confidence > existing.confidence:
            target[index] = ref
        return
    target.append(ref)


def build_visual_reference_map(
    structure: StructuredDocument,
    chunks: Iterable[RetrievalChunk | Mapping[str, Any] | Any],
    *,
    max_page_gap: int = 1,
    max_preceding_chunks: int = 2,
) -> dict[str, list[VisualReference]]:
    """Resolve figures/tables that can safely accompany each text chunk.

    This is the Option-A relationship resolver. It never reads image semantics and
    never changes retrieval rank. Direct canonical relationships are strongest.
    A single bounded heuristic additionally links an explicitly introduced figure
    to the nearest preceding chunks in the same canonical section. That covers
    real layouts such as the SC RBA diagram (the explanatory steps are on the
    previous page) and the VASP due-diligence overview without attaching arbitrary
    same-section artwork.
    """

    chunk_rows = [_as_dict(chunk) for chunk in chunks]
    metadata = _chunk_metadata(structure, chunk_rows)
    result: dict[str, list[VisualReference]] = {str(row["chunk_id"]): [] for row in chunk_rows}
    element_by_id = {
        element.element_id: element
        for page in structure.pages
        for element in page.elements
    }

    # Canonical figure relationships: the source element can be the figure itself,
    # its introduction/caption, a following explanation, or its source note.
    for figure in structure.figures:
        if not _figure_is_displayable(figure, element_by_id):
            continue
        visual_element = element_by_id.get(figure.element_id)
        if visual_element is None:
            continue
        label = _figure_label(figure, element_by_id)
        relation_sets: list[tuple[str, set[str], float]] = [
            ("contains_visual", {figure.element_id}, 1.0),
            ("figure_explanation", set(figure.explanation_element_ids), 0.99),
            ("figure_caption", set(figure.caption_element_ids), 0.97),
            ("figure_intro", set(figure.intro_element_ids), 0.95),
            ("figure_source", set(figure.source_element_ids), 0.88),
        ]
        direct_chunk_ids: set[str] = set()
        for chunk_id, info in metadata.items():
            source_ids = info["source_ids"]
            for relation, relation_ids, confidence in relation_sets:
                overlap = source_ids & relation_ids
                if not overlap:
                    continue
                _append_ref(result[chunk_id], VisualReference(
                    visual_id=figure.figure_id,
                    asset_type="figure",
                    page_number=int(figure.page_number),
                    bbox=[float(value) for value in visual_element.bbox],
                    section_id=figure.section_id,
                    label=label,
                    relation=relation,
                    confidence=confidence,
                    relation_element_ids=sorted(overlap, key=lambda element_id: int(element_by_id[element_id].document_order)),
                ))
                direct_chunk_ids.add(chunk_id)
                break

        # Cross-page / nearby support is deliberately narrow: only an explicit
        # introduction such as "steps above are illustrated in the diagram below"
        # or "an overview ... is set out in Illustration 1 below" can activate it.
        intro_text = _ordered_text(element_by_id, figure.intro_element_ids)
        if (
            not figure.section_id
            or not intro_text
            or not _EXPLICIT_VISUAL_REFERENCE_RE.search(intro_text)
            or not _SUMMARY_REFERENCE_RE.search(intro_text)
        ):
            continue

        anchor_orders = [
            int(element_by_id[element_id].document_order)
            for element_id in figure.intro_element_ids
            if element_id in element_by_id
        ]
        anchor_order = min(anchor_orders) if anchor_orders else int(visual_element.document_order)
        candidates: list[tuple[int, str, dict[str, Any]]] = []
        for chunk_id, info in metadata.items():
            if chunk_id in direct_chunk_ids:
                continue
            max_order = info["max_order"]
            if max_order is None or int(max_order) >= anchor_order:
                continue
            if figure.section_id not in info["section_ids"]:
                continue
            if _page_gap(info["pages"], int(figure.page_number)) > max_page_gap:
                continue
            semantic_type = str(info["chunk"].get("semantic_type") or "")
            if semantic_type in {"figure", "table", "document_metadata"}:
                continue
            candidates.append((int(max_order), chunk_id, info))

        candidates.sort(key=lambda item: item[0], reverse=True)
        for offset, (_, chunk_id, _) in enumerate(candidates[:max_preceding_chunks]):
            confidence = max(0.72, 0.84 - (0.06 * offset))
            _append_ref(result[chunk_id], VisualReference(
                visual_id=figure.figure_id,
                asset_type="figure",
                page_number=int(figure.page_number),
                bbox=[float(value) for value in visual_element.bbox],
                section_id=figure.section_id,
                label=label,
                relation="nearby_explicit_reference",
                confidence=confidence,
                relation_element_ids=list(figure.intro_element_ids),
            ))

    # Tables retain structured text as the retrieval source. A visual reference is
    # only attached when the chunk provenance actually contains a canonical table
    # fragment. Cross-page logical tables produce one crop per referenced page.
    for table in structure.tables:
        label = _table_label(table, element_by_id)
        fragments = [
            element_by_id[element_id]
            for element_id in table.fragment_element_ids
            if element_id in element_by_id
        ]
        fragment_ids = {element.element_id for element in fragments}
        if not fragments:
            continue
        for chunk_id, info in metadata.items():
            overlap = info["source_ids"] & fragment_ids
            if not overlap:
                continue
            matched_fragments = [element for element in fragments if element.element_id in overlap]
            for fragment in matched_fragments:
                _append_ref(result[chunk_id], VisualReference(
                    visual_id=table.logical_table_id,
                    asset_type="table",
                    page_number=int(fragment.page_number),
                    bbox=[float(value) for value in fragment.bbox],
                    section_id=table.section_id,
                    label=label,
                    relation="table_content",
                    confidence=1.0,
                    relation_element_ids=[fragment.element_id],
                ))

    for refs in result.values():
        refs.sort(key=lambda ref: (-float(ref.confidence), int(ref.page_number), ref.asset_type, ref.visual_id))
    return result


def visual_reference_map_for_document(document_id: str) -> dict[str, list[VisualReference]]:
    """Best-effort request-time visual enrichment for frozen Stage-5 chunks.

    Visuals are secondary evidence. Failure to read a visual artifact must never
    make text retrieval unavailable, so callers receive an empty map on unexpected
    enrichment errors and the failure is logged for diagnostics.
    """

    try:
        resolved = read_resolved_structure(document_id)
        chunks = read_chunking_artifact(document_id)
        if resolved is None or chunks is None:
            return {}
        return build_visual_reference_map(resolved.structure, chunks.chunks)
    except Exception:
        logger.exception("visuals.resolve.failed document_id=%s", document_id)
        return {}


def enrich_rows_with_visual_refs(document_id: str, rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    reference_map = visual_reference_map_for_document(document_id)
    output: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        row["visual_refs"] = [
            ref.model_dump(mode="json")
            for ref in reference_map.get(str(row.get("chunk_id") or ""), [])
        ]
        output.append(row)
    return output


def structure_for_visual_preview(document_id: str) -> StructuredDocument | None:
    resolved = read_resolved_structure(document_id)
    if resolved is not None:
        return resolved.structure
    return read_structure(document_id)


def visual_crop(
    structure: StructuredDocument,
    *,
    asset_type: str,
    visual_id: str,
    page_number: int | None = None,
) -> tuple[int, list[float]]:
    element_by_id = {
        element.element_id: element
        for page in structure.pages
        for element in page.elements
    }
    if asset_type == "figure":
        figure = next((item for item in structure.figures if item.figure_id == visual_id), None)
        if figure is None or not _figure_is_displayable(figure, element_by_id):
            raise VisualAssetNotFoundError(f"Unknown or non-displayable figure {visual_id!r}.")
        element = element_by_id.get(figure.element_id)
        if element is None:
            raise VisualAssetNotFoundError(f"Figure {visual_id!r} has no canonical element.")
        return int(figure.page_number), [float(value) for value in element.bbox]

    if asset_type == "table":
        table = next((item for item in structure.tables if item.logical_table_id == visual_id), None)
        if table is None:
            raise VisualAssetNotFoundError(f"Unknown table {visual_id!r}.")
        fragments = [
            element_by_id[element_id]
            for element_id in table.fragment_element_ids
            if element_id in element_by_id
        ]
        if not fragments:
            raise VisualAssetNotFoundError(f"Table {visual_id!r} has no canonical fragments.")
        target_page = int(page_number) if page_number is not None else int(fragments[0].page_number)
        page_fragments = [element for element in fragments if int(element.page_number) == target_page]
        if not page_fragments:
            raise VisualAssetNotFoundError(f"Table {visual_id!r} has no fragment on page {target_page}.")
        x0 = min(float(element.bbox[0]) for element in page_fragments)
        y0 = min(float(element.bbox[1]) for element in page_fragments)
        x1 = max(float(element.bbox[2]) for element in page_fragments)
        y1 = max(float(element.bbox[3]) for element in page_fragments)
        return target_page, [x0, y0, x1, y1]

    raise VisualAssetNotFoundError(f"Unsupported visual asset type {asset_type!r}.")
