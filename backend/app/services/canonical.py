from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import re

from app.schemas import (
    CanonicalElement,
    CanonicalSourceTrace,
    CanonicalTable,
    ClauseRecord,
    AppendixRecord,
    LogicalTable,
    FigureRecord,
    StructuralRelation,
    DefinitionEntry,
    DefinitionSubItem,
    DocumentExtraction,
    DocumentRecord,
    LayoutEngineInfo,
    SectionRecord,
    StructuredDocument,
    StructuredPage,
    StructureSummary,
)


BOX_TYPE_MAP = {
    "text": "paragraph",
    "picture": "figure",
    "table": "table",
    "caption": "caption",
    "title": "title",
    "section-header": "section_header",
    "page-header": "page_header",
    "page-footer": "page_footer",
    "list-item": "list_item",
    "footnote": "footnote",
    "formula": "formula",
}

# Content that should be available to Stage 5. Document metadata, running
# headers/footers and figures remain traceable canonical elements but are not
# placed into body_text automatically.
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

NUMBERED_HEADING = re.compile(
    r"^\s*(?:(?:section|chapter)\s+)?(\d+(?:\.\d+){0,5})(?:[.)])?(?=\s|[A-Za-z])\s*",
    re.IGNORECASE,
)
CLAUSE_PREFIX = re.compile(
    r"^\s*(?:(\d+(?:\.\d+){1,5})(?=\s|[A-Za-z])|(\d+)[.)](?=\s|[A-Za-z]))\s*",
    re.IGNORECASE,
)
QUESTION_PREFIX = re.compile(r"^\s*(?:q(?:uestion)?\s*)?\d+\s*[.)]\s*", re.IGNORECASE)
DEFINITION_CONTEXT = re.compile(
    r"\b(?:definitions?|glossary|interpretation|meaning\s+of\s+(?:words|terms))\b",
    re.IGNORECASE,
)
TERMINAL_PUNCTUATION = re.compile(r"[.!?;:]\s*$")
METADATA_HINT = re.compile(
    r"\b(?:issued|revised|updated|effective|published|version|last\s+updated|as\s+of)\b",
    re.IGNORECASE,
)
DATE_SIGNAL = re.compile(
    r"(?:\b\d{1,2}\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{4}\b|"
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2},?\s+\d{4}\b|"
    r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b|"
    r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b|"
    r"\bversion\s+\d+(?:\.\d+)*\b)",
    re.IGNORECASE,
)

APPENDIX_LABEL = re.compile(r"^\s*APPENDIX\s+([A-Z0-9IVXLC]+)\s*$", re.IGNORECASE)
SUBCLAUSE_PREFIX = re.compile(r"^\s*\(([a-z]|[ivxlcdm]+)\)\s*", re.IGNORECASE)
DEFINITION_INTRO = re.compile(r"^\s*(?:means|means[—–-]|refers?\s+to|includes?)\b", re.IGNORECASE)
DEFINITION_ROW_INTRO = re.compile(
    r"\b(?:shall\s+mean|means?[—–-]?|refers?\s+to|includes?|in\s+relation\s+to|"
    r"in\s+the\s+context\s+of|has\s+the\s+meaning\s+of|has\s+the\s+meaning|"
    r"is\s+defined\s+as)\b",
    re.IGNORECASE,
)
FIGURE_LABEL = re.compile(r"\b(?:illustration|figure|diagram|chart)\s*\d*\b", re.IGNORECASE)
FIGURE_INTRO = re.compile(r"\b(?:illustrat(?:ed|ion)|figure|diagram|shown\s+below|set\s+out\s+in|below)\b", re.IGNORECASE)
SOURCE_HINT = re.compile(r"\b(?:source|guidance|reference|for\s+full|https?://|www\.)\b", re.IGNORECASE)
FOOTNOTE_MARKER = re.compile(r"^\s*(?:[¹²³⁴⁵⁶⁷⁸⁹⁰]+|\d+[.)]?|[*†‡])\s*")


def _bbox_from_box(box: dict) -> list[float]:
    return [
        round(float(box.get("x0", 0.0)), 3),
        round(float(box.get("y0", 0.0)), 3),
        round(float(box.get("x1", 0.0)), 3),
        round(float(box.get("y1", 0.0)), 3),
    ]


def _area(bbox: list[float]) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def _intersection(a: list[float], b: list[float]) -> float:
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _overlap_ratio(a: list[float], b: list[float]) -> float:
    denom = min(_area(a), _area(b))
    if denom <= 0:
        return 0.0
    return _intersection(a, b) / denom


def _box_text(box: dict) -> str:
    if box.get("boxclass") == "table" and isinstance(box.get("table"), dict):
        table = box["table"]
        extracted = table.get("extract") or []
        rows = []
        for row in extracted:
            rows.append("\t".join("" if cell is None else str(cell).strip() for cell in row).rstrip())
        text = "\n".join(row for row in rows if row).strip()
        if text:
            return text

    lines: list[str] = []
    for line in box.get("textlines") or []:
        text = "".join(str(span.get("text", "")) for span in line.get("spans") or [])
        text = text.strip()
        if text:
            lines.append(text)
    return "\n".join(lines).strip()


def _canonical_table(box: dict) -> CanonicalTable | None:
    table = box.get("table")
    if not isinstance(table, dict):
        return None
    cells = table.get("extract") or []
    normalized_cells = [[None if cell is None else str(cell) for cell in row] for row in cells]
    return CanonicalTable(
        row_count=int(table.get("row_count") or len(normalized_cells)),
        col_count=int(table.get("col_count") or max((len(row) for row in normalized_cells), default=0)),
        cells=normalized_cells,
        markdown=table.get("markdown"),
    )


def _normalize_heading_text(value: str) -> str:
    value = value.casefold()
    value = re.sub(r"[^\w\s.]", " ", value)
    return re.sub(r"\s+", " ", value).strip(" .")


def _toc_items(layout_result: dict) -> list[tuple[int, str, int]]:
    output: list[tuple[int, str, int]] = []
    for item in layout_result.get("toc") or []:
        if isinstance(item, (list, tuple)) and len(item) >= 3:
            try:
                output.append((int(item[0]), str(item[1]), int(item[2])))
            except (TypeError, ValueError):
                continue
        elif isinstance(item, dict):
            try:
                output.append(
                    (
                        int(item.get("level") or item.get("lvl")),
                        str(item.get("title") or ""),
                        int(item.get("page") or item.get("page_number")),
                    )
                )
            except (TypeError, ValueError):
                continue
    return output


def _match_toc_level(text: str, page_number: int, toc: list[tuple[int, str, int]]) -> int | None:
    candidate = _normalize_heading_text(text)
    if not candidate:
        return None
    for level, title, page in toc:
        if page != page_number:
            continue
        normalized = _normalize_heading_text(title)
        if not normalized:
            continue
        if candidate == normalized:
            return max(1, min(6, level))
        if min(len(candidate), len(normalized)) >= 8 and (
            candidate.startswith(normalized) or normalized.startswith(candidate)
        ):
            return max(1, min(6, level))
    return None


def _numbering_depth(text: str) -> int | None:
    match = NUMBERED_HEADING.match(text)
    if not match:
        return None
    return max(1, min(6, match.group(1).count(".") + 1))


def _normalize_structural_text(text: str) -> str:
    """Repair only structural numbering whitespace, never rewrite prose.

    Layout engines can return ``3.DEFINITIONS`` or ``3.1Unless`` when the
    source has visually separated numbering but no extracted whitespace. The
    canonical layer inserts a single space after the leading structural number
    while leaving the rest of the text untouched.
    """
    if not text:
        return text
    return re.sub(
        r"^(\s*\d+(?:\.\d+){0,5})([.)]?)(?=[A-Za-z])",
        lambda match: f"{match.group(1)}{match.group(2)} ",
        text,
        count=1,
    )


def _extract_clause_number(text: str) -> str | None:
    match = CLAUSE_PREFIX.match(text)
    if not match:
        return None
    return match.group(1) or match.group(2)


def _looks_definition_context(text: str) -> bool:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return False
    return bool(DEFINITION_CONTEXT.search(normalized))


def _looks_definition_term_text(text: str) -> bool:
    text = " ".join(text.split()).strip()
    if not text or len(text) > 100 or text.isdigit():
        return False
    if _looks_definition_context(text) or _looks_document_metadata(text):
        return False
    if _numbering_depth(text) is not None or _extract_clause_number(text) is not None:
        return False
    # Definition terms are labels, not complete questions or long prose. This
    # intentionally uses no domain vocabulary.
    if text.endswith(("?", "!", ".", ";", ":")):
        return False
    return len(text.split()) <= 12


def _looks_short_definition_term(element: CanonicalElement, page_width: float) -> bool:
    if not _looks_definition_term_text(element.text):
        return False
    x0, _, x1, _ = element.bbox
    width = max(0.0, x1 - x0)
    if page_width <= 0:
        return False
    return x0 <= page_width * 0.46 and width <= page_width * 0.42

def _same_row(term: CanonicalElement, candidate: CanonicalElement) -> bool:
    term_y0, term_y1 = term.bbox[1], term.bbox[3]
    cand_y0, cand_y1 = candidate.bbox[1], candidate.bbox[3]
    overlap = max(0.0, min(term_y1, cand_y1) - max(term_y0, cand_y0))
    min_height = max(1.0, min(term_y1 - term_y0, cand_y1 - cand_y0))
    if overlap / min_height >= 0.2:
        return True
    return abs(term_y0 - cand_y0) <= 16.0


def _text_looks_incomplete(text: str) -> bool:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return False
    return TERMINAL_PUNCTUATION.search(normalized) is None


def _looks_question(text: str) -> bool:
    text = " ".join(text.split()).strip()
    if not text:
        return False
    if text.endswith("?"):
        return True
    return bool(QUESTION_PREFIX.match(text) and "?" in text)


def _looks_document_metadata(text: str) -> bool:
    text = " ".join(text.split()).strip()
    if not text or len(text) > 240:
        return False
    if not METADATA_HINT.search(text):
        return False
    return bool(DATE_SIGNAL.search(text) or ":" in text or ";" in text)


def _is_centered(element: CanonicalElement, page_width: float) -> bool:
    if page_width <= 0:
        return False
    x0, _, x1, _ = element.bbox
    center = (x0 + x1) / 2
    return abs(center - page_width / 2) <= page_width * 0.16


def _weighted_median(values: list[tuple[float, int]]) -> float | None:
    values = [(value, max(weight, 1)) for value, weight in values if value > 0]
    if not values:
        return None
    values.sort(key=lambda item: item[0])
    total = sum(weight for _, weight in values)
    midpoint = total / 2
    running = 0
    for value, weight in values:
        running += weight
        if running >= midpoint:
            return round(value, 3)
    return round(values[-1][0], 3)


def _dominant_font_size(page_extraction, bbox: list[float]) -> float | None:
    weighted: list[tuple[float, int]] = []
    for block in page_extraction.blocks:
        if getattr(block, "type", None) != "text" or _overlap_ratio(block.bbox, bbox) < 0.15:
            continue
        for line in block.lines:
            for span in line.spans:
                if span.size is None or _overlap_ratio(span.bbox, bbox) < 0.35:
                    continue
                weighted.append((float(span.size), len(span.text.strip())))
    return _weighted_median(weighted)


def _source_trace(page_extraction, bbox: list[float], box_index: int, boxclass: str) -> CanonicalSourceTrace:
    block_ids = [
        block.block_id
        for block in page_extraction.blocks
        if _overlap_ratio(block.bbox, bbox) >= 0.35
    ]
    table_ids = [
        table.table_id
        for table in page_extraction.tables
        if _overlap_ratio(table.bbox, bbox) >= 0.35
    ]
    return CanonicalSourceTrace(
        layout_box_index=box_index,
        layout_box_class=boxclass,
        stage3_block_ids=block_ids,
        stage3_table_ids=table_ids,
    )


def _refine_document_roles(
    elements: list[CanonicalElement],
    pages: list[StructuredPage],
) -> tuple[CanonicalElement | None, CanonicalElement | None, list[CanonicalElement]]:
    """Conservatively repair document-level roles on the first page.

    Layout engines are good at locating header-like regions but may label a cover
    title, subtitle, version line and the first real section all as
    ``section-header``. This pass uses only geometric and textual evidence; it
    does not call an LLM and it preserves the vendor class in ``source``.
    """
    if not pages:
        return None, None, []

    first_page = pages[0]
    first_page_elements = sorted(first_page.elements, key=lambda item: item.reading_order)
    if not first_page_elements:
        return None, None, []

    page_height = max(first_page.height, 1.0)
    page_width = max(first_page.width, 1.0)
    top_limit = page_height * 0.32

    header_like = [
        element
        for element in first_page_elements
        if element.type in {"title", "section_header"}
        and element.text.strip()
        and element.bbox[1] <= top_limit
    ]

    metadata_elements: list[CanonicalElement] = []
    for element in header_like:
        if _looks_document_metadata(element.text):
            element.type = "document_metadata"
            element.role_source = "metadata_pattern"
            element.heading_level = None
            element.heading_level_source = None
            metadata_elements.append(element)

    usable = [element for element in header_like if element.type != "document_metadata"]

    # Prefer the vendor's explicit title label. If it missed the title, promote
    # a centered, non-numbered top heading. This keeps the heuristic conservative
    # and avoids turning a left-aligned "1 Introduction" into a document title.
    explicit_titles = [element for element in usable if element.source.layout_box_class == "title"]
    if explicit_titles:
        title_element = explicit_titles[0]
        title_element.type = "title"
        title_element.role_source = "layout_title"
    else:
        title_element = next(
            (
                element
                for element in usable
                if element.type == "section_header"
                and _is_centered(element, page_width)
                and _numbering_depth(element.text) is None
                and not _looks_question(element.text)
                and len(" ".join(element.text.split())) <= 160
                and element.bbox[1] <= page_height * 0.24
            ),
            None,
        )
        if title_element is not None:
            title_element.type = "title"
            title_element.role_source = "promoted_top_heading"

    subtitle_element: CanonicalElement | None = None
    if title_element is not None:
        title_bottom = title_element.bbox[3]
        subtitle_element = next(
            (
                element
                for element in usable
                if element.element_id != title_element.element_id
                and element.type in {"title", "section_header"}
                and element.reading_order > title_element.reading_order
                and element.bbox[1] >= title_bottom - 3
                and element.bbox[1] - title_bottom <= page_height * 0.12
                and _is_centered(element, page_width)
                and _numbering_depth(element.text) is None
                and not _looks_question(element.text)
                and not _looks_document_metadata(element.text)
                and len(" ".join(element.text.split())) <= 180
            ),
            None,
        )
        if subtitle_element is not None:
            subtitle_element.type = "subtitle"
            subtitle_element.role_source = "title_cluster_subtitle"
            subtitle_element.heading_level = None
            subtitle_element.heading_level_source = None

    # Any extra vendor title after the selected title must not remain a second
    # document title. If it is not a subtitle, treat it as a section header so
    # it can participate in the normal hierarchy pass.
    for element in elements:
        if element.type != "title" or element is title_element:
            continue
        if subtitle_element is not None and element is subtitle_element:
            continue
        element.type = "section_header"
        element.role_source = "demoted_extra_layout_title"

    return title_element, subtitle_element, metadata_elements


def _normalize_structural_elements(elements: list[CanonicalElement]) -> None:
    for element in elements:
        if element.type in {"section_header", "list_item"}:
            element.text = _normalize_structural_text(element.text)


def _refine_numbered_clauses(elements: list[CanonicalElement]) -> None:
    """Promote numbered prose clauses and nested alphabetic subclauses.

    This pass keeps outline sections separate from legal/procedural clauses.
    It accepts both decimal clauses (``2.5`` / ``3.1``) and top-level numbered
    clauses (``1.`` / ``2.``), while question headings remain section headers.
    """
    for element in elements:
        if element.type not in {"paragraph", "list_item"}:
            continue

        number = _extract_clause_number(element.text)
        if number is not None:
            remainder = CLAUSE_PREFIX.sub("", element.text, count=1).strip()
            if len(remainder) >= 12 and not _looks_question(element.text):
                element.type = "clause"
                element.clause_number = number
                element.text = _normalize_structural_text(element.text)
                element.role_source = "numbered_clause"
                continue

        marker = SUBCLAUSE_PREFIX.match(element.text)
        if marker:
            remainder = SUBCLAUSE_PREFIX.sub("", element.text, count=1).strip()
            if len(remainder) >= 8:
                element.type = "subclause"
                element.subclause_marker = f"({marker.group(1)})"
                element.role_source = "subclause_marker"


def _definition_context_pages(
    elements: list[CanonicalElement],
    pages: list[StructuredPage],
) -> set[int]:
    """Return pages that are inside a Definitions / Glossary-like section.

    Vendor layout engines sometimes misclassify a continuation fragment at the
    top of the next page as ``section-header``. A naive hierarchy walk would
    therefore close the Definitions section too early. We only end an active
    definition context on a *strong* structural boundary: a numbered or appendix
    heading at the same/higher hierarchy, or an unnumbered same/higher-level
    heading that is positioned in the document's left/central heading region.

    This is intentionally geometry- and hierarchy-based; it does not depend on
    any specific glossary term or page number.
    """
    active = False
    active_level: int | None = None
    context_pages: set[int] = set()
    page_width = {page.page_number: max(page.width, 1.0) for page in pages}

    for element in sorted(elements, key=lambda item: item.document_order):
        if element.type == "section_header":
            if _looks_definition_context(element.text):
                active = True
                active_level = element.heading_level
            elif active:
                same_or_higher = (
                    element.heading_level is not None
                    and active_level is not None
                    and element.heading_level <= active_level
                )
                numbered_boundary = _numbering_depth(element.text) is not None
                appendix_boundary = APPENDIX_LABEL.match(element.text) is not None
                width = page_width.get(element.page_number, 1.0)
                left_or_center_heading = element.bbox[0] <= width * 0.42
                strong_unnumbered_boundary = same_or_higher and left_or_center_heading

                if appendix_boundary or (same_or_higher and numbered_boundary) or strong_unnumbered_boundary:
                    active = False
                    active_level = None

        if active:
            context_pages.add(element.page_number)

    return context_pages


def _definition_text_candidate(element: CanonicalElement, page_width: float) -> bool:
    text = " ".join(element.text.split()).strip()
    if len(text) < 12 or text.isdigit():
        return False
    if element.type in {
        "title",
        "subtitle",
        "document_metadata",
        "section_header",
        "definition_term",
        "page_header",
        "figure",
        "table",
    }:
        return False
    return element.bbox[0] >= page_width * 0.38



def _looks_definition_table_header(term: str, definition: str) -> bool:
    """Reject obvious glossary header rows without depending on a specific PDF."""
    left = re.sub(r"[^a-z ]", " ", term.casefold())
    right = re.sub(r"[^a-z ]", " ", definition.casefold())
    left = " ".join(left.split())
    right = " ".join(right.split())
    left_headers = {"term", "terms", "word", "words", "expression", "expressions", "abbreviation", "abbreviations"}
    right_headers = {"definition", "definitions", "meaning", "meanings", "description", "descriptions"}
    return left in left_headers and right in right_headers


def _definition_table_rows(element: CanonicalElement) -> list[tuple[str, str]]:
    """Return glossary-like term/definition rows from a table element.

    The canonical layer deliberately ignores the vendor's choice between text
    columns and a detected table. A table qualifies only when most non-empty
    rows have a short first column and substantive text to the right.
    """
    if element.type != "table" or element.table is None or element.table.col_count < 2:
        return []

    rows: list[tuple[str, str]] = []
    considered = 0
    for row in element.table.cells:
        if not row:
            continue
        term = " ".join(str(row[0] or "").split()).strip()
        definition = " ".join(
            " ".join(str(cell or "").split()).strip()
            for cell in row[1:]
            if str(cell or "").strip()
        ).strip()
        if not term and not definition:
            continue
        if _looks_definition_table_header(term, definition):
            continue
        considered += 1
        if term and len(term) <= 100 and len(term.split()) <= 12 and len(definition) >= 8:
            rows.append((term, definition))

    if considered == 0 or len(rows) / considered < 0.6:
        return []
    return rows


def _existing_definition_pairs_on_page(page: StructuredPage) -> list[tuple[CanonicalElement, CanonicalElement]]:
    """Find already-separated term/definition rows before any recovery."""
    page_width = max(page.width, 1.0)
    terms = [
        element
        for element in page.elements
        if element.type in {"section_header", "paragraph", "list_item", "page_footer", "definition_term"}
        and _looks_short_definition_term(element, page_width)
    ]
    definitions = [
        element for element in page.elements if _definition_text_candidate(element, page_width)
    ]
    pairs: list[tuple[CanonicalElement, CanonicalElement]] = []
    for term in terms:
        possible = [
            candidate
            for candidate in definitions
            if candidate.element_id != term.element_id
            and candidate.bbox[0] >= term.bbox[2] + max(18.0, page_width * 0.045)
            and _same_row(term, candidate)
        ]
        if possible:
            pairs.append((term, min(possible, key=lambda item: abs(item.bbox[1] - term.bbox[1]))))
    return pairs


def _definition_column_model(
    pages: list[StructuredPage], definition_pages: set[int]
) -> dict[str, float] | None:
    """Learn a normalized two-column glossary model from reliable rows."""
    split_ratios: list[float] = []
    definition_left_ratios: list[float] = []
    term_left_ratios: list[float] = []
    term_right_ratios: list[float] = []
    for page in pages:
        if page.page_number not in definition_pages:
            continue
        width = max(page.width, 1.0)
        for term, definition in _existing_definition_pairs_on_page(page):
            gap = definition.bbox[0] - term.bbox[2]
            if gap < max(12.0, width * 0.025):
                continue
            split_ratios.append(((term.bbox[2] + definition.bbox[0]) / 2.0) / width)
            definition_left_ratios.append(definition.bbox[0] / width)
            term_left_ratios.append(term.bbox[0] / width)
            term_right_ratios.append(term.bbox[2] / width)
    split = _median(split_ratios)
    def_left = _median(definition_left_ratios)
    term_left = _median(term_left_ratios)
    term_right = _median(term_right_ratios)
    if split is None:
        return None
    return {
        "split_ratio": split,
        "definition_left_ratio": def_left if def_left is not None else split,
        "term_left_ratio": term_left if term_left is not None else 0.0,
        "term_right_ratio": term_right if term_right is not None else split,
        "sample_count": float(len(split_ratios)),
    }


def _union_bbox(boxes: list[list[float]]) -> list[float] | None:
    if not boxes:
        return None
    return [
        round(min(box[0] for box in boxes), 3),
        round(min(box[1] for box in boxes), 3),
        round(max(box[2] for box in boxes), 3),
        round(max(box[3] for box in boxes), 3),
    ]


def _stage3_lines_in_region(raw_page, bbox: list[float]) -> list[dict]:
    """Return Stage-3 lines/spans intersecting a canonical region."""
    output: list[dict] = []
    for block in raw_page.blocks:
        if getattr(block, "type", None) != "text" or _intersection(block.bbox, bbox) <= 0:
            continue
        for line in block.lines:
            if _intersection(line.bbox, bbox) <= 0:
                continue
            spans = [
                span
                for span in line.spans
                if span.text.strip() and _intersection(span.bbox, bbox) > 0
            ]
            if spans:
                output.append({"bbox": list(line.bbox), "spans": spans})
    return sorted(output, key=lambda item: (item["bbox"][1], item["bbox"][0]))


def _infer_definition_split_x(
    *, raw_lines: list[dict], element: CanonicalElement, page_width: float, model: dict[str, float] | None
) -> float | None:
    if model is not None:
        split = model["split_ratio"] * page_width
        if element.bbox[0] + page_width * 0.08 < split < element.bbox[2] - page_width * 0.08:
            return split

    spans = [span for line in raw_lines for span in line["spans"]]
    if len(spans) < 2:
        return None
    ordered = sorted(spans, key=lambda span: span.bbox[0])
    gaps: list[tuple[float, float]] = []
    for left, right in zip(ordered, ordered[1:]):
        gap = right.bbox[0] - left.bbox[2]
        split = (left.bbox[2] + right.bbox[0]) / 2.0
        if gap >= max(18.0, page_width * 0.04) and element.bbox[0] < split < element.bbox[2]:
            gaps.append((gap, split))
    return max(gaps, default=(0.0, None), key=lambda item: item[0])[1]


def _valid_recovered_definition_row(term: str, definition: str) -> bool:
    term = " ".join(term.split()).strip()
    definition = " ".join(definition.split()).strip()
    return _looks_definition_term_text(term) and len(definition) >= 8


def _recover_rows_from_stage3_columns(
    *, raw_page, element: CanonicalElement, page_width: float, model: dict[str, float] | None
) -> list[dict]:
    """Recover one or more logical glossary rows from Stage-3 span geometry."""
    raw_lines = _stage3_lines_in_region(raw_page, element.bbox)
    split_x = _infer_definition_split_x(
        raw_lines=raw_lines, element=element, page_width=page_width, model=model
    )
    if split_x is None:
        return []

    rows: list[dict] = []
    current: dict | None = None
    pending_left_text: list[str] = []
    pending_left_boxes: list[list[float]] = []

    for line in raw_lines:
        left_spans = []
        right_spans = []
        crossing = False
        for span in line["spans"]:
            center = (span.bbox[0] + span.bbox[2]) / 2.0
            if span.bbox[0] < split_x < span.bbox[2] and (span.bbox[2] - span.bbox[0]) > page_width * 0.25:
                crossing = True
            if center < split_x:
                left_spans.append(span)
            else:
                right_spans.append(span)

        if crossing and len(line["spans"]) == 1:
            continue

        left_text = " ".join(span.text.strip() for span in left_spans if span.text.strip()).strip()
        right_text = " ".join(span.text.strip() for span in right_spans if span.text.strip()).strip()
        left_boxes = [list(span.bbox) for span in left_spans]
        right_boxes = [list(span.bbox) for span in right_spans]
        line_y0 = float(line["bbox"][1])
        line_y1 = float(line["bbox"][3])
        line_height = max(1.0, line_y1 - line_y0)

        if left_text and right_text:
            close_to_current = bool(
                current and line_y0 - current["last_y1"] <= max(8.0, line_height * 1.25)
            )
            if close_to_current:
                current["term_parts"].append(left_text)
                current["definition_parts"].append(right_text)
                current["term_boxes"].extend(left_boxes)
                current["definition_boxes"].extend(right_boxes)
                current["last_y1"] = line_y1
            else:
                if current:
                    rows.append(current)
                current = {
                    "term_parts": pending_left_text + [left_text],
                    "definition_parts": [right_text],
                    "term_boxes": pending_left_boxes + left_boxes,
                    "definition_boxes": right_boxes,
                    "last_y1": line_y1,
                }
                pending_left_text = []
                pending_left_boxes = []
        elif right_text:
            if current:
                current["definition_parts"].append(right_text)
                current["definition_boxes"].extend(right_boxes)
                current["last_y1"] = line_y1
        elif left_text:
            if current and line_y0 - current["last_y1"] <= max(8.0, line_height * 1.25):
                current["term_parts"].append(left_text)
                current["term_boxes"].extend(left_boxes)
                current["last_y1"] = line_y1
            else:
                pending_left_text.append(left_text)
                pending_left_boxes.extend(left_boxes)

    if current:
        rows.append(current)

    recovered: list[dict] = []
    for row in rows:
        term = " ".join(row["term_parts"]).strip()
        definition = " ".join(row["definition_parts"]).strip()
        term_bbox = _union_bbox(row["term_boxes"])
        definition_bbox = _union_bbox(row["definition_boxes"])
        if term_bbox and definition_bbox and _valid_recovered_definition_row(term, definition):
            recovered.append({
                "term": term,
                "definition": definition,
                "term_bbox": term_bbox,
                "definition_bbox": definition_bbox,
                "source": "definition_row_recovery_span_columns",
            })
    return recovered


def _recover_row_from_text_pattern(
    *, element: CanonicalElement, page_width: float, model: dict[str, float] | None
) -> list[dict]:
    """Fallback for merged text where Stage-3 has only one spanning text run."""
    normalized = " ".join(element.text.split()).strip()
    match = DEFINITION_ROW_INTRO.search(normalized)
    if not match or match.start() <= 0:
        return []
    term = normalized[: match.start()].strip(" :-–—")
    definition = normalized[match.start() :].strip()
    if not _valid_recovered_definition_row(term, definition):
        return []

    if model is not None:
        term_right = model.get("term_right_ratio", model["split_ratio"]) * page_width
        definition_left = model.get("definition_left_ratio", model["split_ratio"]) * page_width
    else:
        split_x = element.bbox[0] + (element.bbox[2] - element.bbox[0]) * 0.43
        gap = max(18.0, page_width * 0.05)
        term_right = split_x - gap / 2.0
        definition_left = split_x + gap / 2.0

    term_right = min(max(term_right, element.bbox[0] + 8.0), element.bbox[2] - 20.0)
    definition_left = min(max(definition_left, term_right + max(18.0, page_width * 0.045)), element.bbox[2] - 8.0)
    return [{
        "term": term,
        "definition": definition,
        "term_bbox": [element.bbox[0], element.bbox[1], round(term_right, 3), element.bbox[3]],
        "definition_bbox": [round(definition_left, 3), element.bbox[1], element.bbox[2], element.bbox[3]],
        "source": "definition_row_recovery_text_pattern",
    }]


def _merged_definition_region_candidate(element: CanonicalElement, page_width: float) -> bool:
    if element.definition_entry_id is not None or element.type not in {"paragraph", "list_item"}:
        return False
    if not element.text.strip() or _looks_document_metadata(element.text):
        return False
    width = max(0.0, element.bbox[2] - element.bbox[0])
    return (
        width >= page_width * 0.52
        and element.bbox[0] <= page_width * 0.38
        and element.bbox[2] >= page_width * 0.68
    )


def _reindex_canonical_elements(elements: list[CanonicalElement], pages: list[StructuredPage]) -> None:
    document_order = 0
    rebuilt: list[CanonicalElement] = []
    for page in sorted(pages, key=lambda item: item.page_number):
        for reading_order, element in enumerate(page.elements):
            element.reading_order = reading_order
            element.document_order = document_order
            document_order += 1
            rebuilt.append(element)
    elements[:] = rebuilt


def _recover_merged_definition_rows(
    *,
    elements: list[CanonicalElement],
    pages: list[StructuredPage],
    extraction_by_page: dict[int, object],
    definition_pages: set[int],
) -> int:
    """Normalize merged glossary rows before the normal definition grouping pass."""
    model = _definition_column_model(pages, definition_pages)
    recovered_count = 0

    for page in pages:
        if page.page_number not in definition_pages:
            continue
        raw_page = extraction_by_page.get(page.page_number)
        if raw_page is None:
            continue
        page_width = max(page.width, 1.0)
        new_elements: list[CanonicalElement] = []

        for element in page.elements:
            if not _merged_definition_region_candidate(element, page_width):
                new_elements.append(element)
                continue

            rows = _recover_rows_from_stage3_columns(
                raw_page=raw_page,
                element=element,
                page_width=page_width,
                model=model,
            )
            if not rows:
                rows = _recover_row_from_text_pattern(
                    element=element,
                    page_width=page_width,
                    model=model,
                )
            if not rows:
                new_elements.append(element)
                continue

            for row_index, row in enumerate(rows, start=1):
                term = element.model_copy(deep=True)
                definition = element.model_copy(deep=True)
                base_id = element.element_id
                term.element_id = f"{base_id}-r{row_index}-term"
                definition.element_id = f"{base_id}-r{row_index}-definition"

                term.type = "definition_term"
                term.text = row["term"]
                term.bbox = row["term_bbox"]
                term.definition_entry_id = None
                term.heading_level = None
                term.heading_level_source = None
                term.table = None
                term.role_source = row["source"]

                definition.type = "definition_text"
                definition.text = row["definition"]
                definition.bbox = row["definition_bbox"]
                definition.definition_entry_id = None
                definition.heading_level = None
                definition.heading_level_source = None
                definition.table = None
                definition.role_source = row["source"]

                new_elements.extend([term, definition])
                recovered_count += 1

        page.elements = new_elements

    if recovered_count:
        _reindex_canonical_elements(elements, pages)
    return recovered_count


def _parse_definition_items(text: str) -> list[DefinitionSubItem]:
    normalized = " ".join(text.split()).strip()
    matches = list(re.finditer(r"(?:^|\s)(\([a-z]\))\s+", normalized, re.IGNORECASE))
    if len(matches) < 2:
        return []
    items: list[DefinitionSubItem] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        value = normalized[start:end].strip(" ;")
        if value:
            items.append(DefinitionSubItem(marker=match.group(1), text=value))
    return items


def _median(values: list[float]) -> float | None:
    values = sorted(float(value) for value in values)
    if not values:
        return None
    midpoint = len(values) // 2
    if len(values) % 2:
        return values[midpoint]
    return (values[midpoint - 1] + values[midpoint]) / 2


def _horizontal_overlap_ratio(a: list[float], b: list[float]) -> float:
    overlap = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    denom = max(1.0, min(a[2] - a[0], b[2] - b[0]))
    return overlap / denom


def _definition_column_profile(parts: list[CanonicalElement]) -> list[float] | None:
    if not parts:
        return None
    x0 = _median([part.bbox[0] for part in parts])
    x1 = _median([part.bbox[2] for part in parts])
    if x0 is None or x1 is None or x1 <= x0:
        return None
    return [x0, 0.0, x1, 1.0]


def _is_strong_cross_page_boundary(element: CanonicalElement, page_width: float) -> bool:
    """Return True only for elements that should stop a continuation scan.

    A vendor ``section-header`` is not automatically a hard boundary because
    continuation fragments such as ``the context.`` are sometimes labelled as
    headers. Numbering, appendix labels, title-like geometry and explicit
    definition terms/tables provide stronger evidence.
    """
    text = " ".join(element.text.split()).strip()
    if not text:
        return False
    if element.type in {"title", "subtitle", "document_metadata", "figure"}:
        return True
    if element.type == "definition_term":
        return True
    if element.type == "table" and _definition_table_rows(element):
        return True
    if element.type in {"clause", "subclause"}:
        return True
    if APPENDIX_LABEL.match(text) or _numbering_depth(text) is not None:
        return True
    if element.type == "section_header":
        # A genuine unnumbered section heading is generally left/central rather
        # than deep in the right-hand continuation column.
        return element.bbox[0] <= page_width * 0.42 and len(text) <= 180
    return False


def _definition_open_score(
    *,
    page: StructuredPage,
    parts: list[CanonicalElement],
    last_part: CanonicalElement,
) -> tuple[int, list[str]]:
    score = 0
    evidence: list[str] = []
    if last_part.bbox[3] >= page.height * 0.72:
        score += 3
        evidence.append("last definition fragment is near the page bottom")
    elif last_part.bbox[3] >= page.height * 0.62:
        score += 1
        evidence.append("last definition fragment is in the lower page region")

    later_meaningful = [
        element
        for element in page.elements
        if element.document_order > last_part.document_order
        and element.type not in {"page_footer", "page_header", "footnote"}
        and element.text.strip()
    ]
    if not later_meaningful:
        score += 2
        evidence.append("no later body element appears on the page")

    if _text_looks_incomplete(last_part.text):
        score += 2
        evidence.append("last fragment appears textually incomplete")

    if len(parts) >= 1:
        score += 1
        evidence.append("definition entry has an established right-column content region")
    return score, evidence


def _definition_continuation_score(
    *,
    previous_part: CanonicalElement,
    candidate: CanonicalElement,
    expected_column: list[float],
    next_page: StructuredPage,
    first_candidate: bool,
) -> tuple[int, list[str]]:
    score = 0
    evidence: list[str] = []
    width = max(next_page.width, 1.0)

    x0_delta = abs(candidate.bbox[0] - expected_column[0])
    if x0_delta <= width * 0.045:
        score += 3
        evidence.append("left edge aligns with the previous definition column")
    elif x0_delta <= width * 0.09:
        score += 1
        evidence.append("left edge is approximately aligned with the previous definition column")

    overlap = _horizontal_overlap_ratio(candidate.bbox, expected_column)
    if overlap >= 0.65:
        score += 2
        evidence.append("horizontal range overlaps the previous definition column")
    elif overlap >= 0.4:
        score += 1
        evidence.append("horizontal range partially overlaps the previous definition column")

    if first_candidate and candidate.bbox[1] <= next_page.height * 0.28:
        score += 2
        evidence.append("candidate begins near the top of the next page")

    if previous_part.dominant_font_size and candidate.dominant_font_size:
        if abs(previous_part.dominant_font_size - candidate.dominant_font_size) <= 1.5:
            score += 1
            evidence.append("font size is compatible across the page break")

    text = " ".join(candidate.text.split()).strip()
    if text and not _is_strong_cross_page_boundary(candidate, width):
        score += 1
        evidence.append("candidate is not a strong structural boundary")
    if text and (text[:1].islower() or DEFINITION_INTRO.match(text)):
        score += 1
        evidence.append("text begins like prose/definition continuation")
    if _text_looks_incomplete(previous_part.text):
        score += 1
        evidence.append("previous fragment is incomplete")

    return score, evidence


def _reconcile_cross_page_definition_continuations(
    *,
    pages: list[StructuredPage],
    definition_pages: set[int],
    page_entry_ids: dict[int, list[str]],
) -> list[StructuralRelation]:
    """Reconcile definition entries that continue over a page boundary.

    The decision is multi-signal and intentionally term-agnostic: it uses the
    established definition column, page-boundary geometry, section context,
    typography, textual completeness and structural boundaries. It can also
    repair vendor mislabels such as a continuation fragment marked as a
    ``section-header``. Weak evidence is left unmerged.
    """
    relations: list[StructuralRelation] = []
    ordered_pages = sorted(pages, key=lambda item: item.page_number)

    for page_index, page in enumerate(ordered_pages[:-1]):
        if page.page_number not in definition_pages:
            continue
        ids = page_entry_ids.get(page.page_number) or []
        if not ids:
            continue

        last_id = ids[-1]
        current_parts = sorted(
            [
                element
                for element in page.elements
                if element.definition_entry_id == last_id and element.type == "definition_text"
            ],
            key=lambda item: item.document_order,
        )
        if not current_parts:
            continue
        last_part = current_parts[-1]
        expected_column = _definition_column_profile(current_parts)
        if expected_column is None:
            continue

        open_score, open_evidence = _definition_open_score(
            page=page, parts=current_parts, last_part=last_part
        )
        if open_score < 4:
            continue

        next_page = ordered_pages[page_index + 1]
        # The next page may itself have been incorrectly dropped from the
        # definition context because a continuation fragment was labelled as a
        # section header. We therefore evaluate it directly, but require strong
        # geometry/context evidence before merging.
        page_width = max(next_page.width, 1.0)

        next_terms = sorted(
            [element for element in next_page.elements if element.type == "definition_term"],
            key=lambda item: item.bbox[1],
        )
        definition_tables = sorted(
            [element for element in next_page.elements if _definition_table_rows(element)],
            key=lambda item: item.bbox[1],
        )

        cutoffs: list[float] = []
        if next_terms:
            cutoffs.append(next_terms[0].bbox[1] - 4.0)
        if definition_tables:
            cutoffs.append(definition_tables[0].bbox[1] - 4.0)

        # A genuine structural heading before any continuation also stops the
        # scan. A right-column pseudo-heading is deliberately *not* treated as
        # a boundary until its continuation score is evaluated.
        for element in sorted(next_page.elements, key=lambda item: item.reading_order):
            if element.type in {"page_header", "page_footer", "footnote"} or not element.text.strip():
                continue
            if _is_strong_cross_page_boundary(element, page_width):
                if element.type != "definition_term" and not (element.type == "table" and _definition_table_rows(element)):
                    cutoffs.append(element.bbox[1] - 4.0)
                break

        cutoff_y = min(cutoffs) if cutoffs else float("inf")
        candidates = [
            element
            for element in sorted(next_page.elements, key=lambda item: item.reading_order)
            if element.definition_entry_id is None
            and element.bbox[1] < cutoff_y
            and element.type not in {"page_header", "page_footer", "footnote", "figure", "table", "title", "subtitle", "document_metadata"}
            and element.text.strip()
        ]
        if not candidates:
            continue

        first = candidates[0]
        first_score, first_evidence = _definition_continuation_score(
            previous_part=last_part,
            candidate=first,
            expected_column=expected_column,
            next_page=next_page,
            first_candidate=True,
        )
        # Both the previous page and next-page candidate must independently
        # provide credible evidence. This prevents accidental merges merely
        # because a paragraph happens to start near the top of the next page.
        if first_score < 6 or open_score + first_score < 11:
            continue

        attached: list[CanonicalElement] = []
        previous = last_part
        for index, element in enumerate(candidates):
            if index > 0 and _is_strong_cross_page_boundary(element, page_width):
                break
            score, _ = _definition_continuation_score(
                previous_part=previous,
                candidate=element,
                expected_column=expected_column,
                next_page=next_page,
                first_candidate=(index == 0),
            )
            if index == 0:
                if score < 6:
                    break
            else:
                # Once continuation is established, subsequent blocks can be
                # accepted with slightly weaker evidence, but they must still
                # remain in the same definition column.
                if score < 4:
                    break

            element.type = "definition_text"
            element.text = " ".join(element.text.split()).strip()
            element.definition_entry_id = last_id
            element.role_source = "cross_page_definition_reconciliation"
            element.heading_level = None
            element.heading_level_source = None
            attached.append(element)
            previous = element

        if not attached:
            continue

        evidence = "; ".join(open_evidence + first_evidence)
        relations.append(
            StructuralRelation(
                relation_id=f"rel-definition-{len(relations) + 1}",
                type="continues",
                source_element_id=last_part.element_id,
                target_element_id=attached[0].element_id,
                evidence=f"cross-page definition continuation score={open_score + first_score}: {evidence}",
            )
        )

        # Keep the next page inside the definition context for subsequent
        # per-document reasoning even if the vendor emitted a pseudo-heading.
        definition_pages.add(next_page.page_number)

    return relations


def _refine_definition_lists(
    elements: list[CanonicalElement],
    pages: list[StructuredPage],
    extraction_by_page: dict[int, object],
) -> list[StructuralRelation]:
    """Reconstruct glossary / definition-list rows from repeated page geometry.

    This pass is deliberately restricted to an active Definitions/Glossary-like
    section. Within that context a short label in the left column must have a
    substantial text region aligned on the same row in the right column. This
    lets us repair vendor mistakes such as a term labelled ``section-header`` or
    ``page-footer`` without hard-coding any particular legal term.
    """
    definition_pages = _definition_context_pages(elements, pages)
    if not definition_pages:
        return []

    _recover_merged_definition_rows(
        elements=elements,
        pages=pages,
        extraction_by_page=extraction_by_page,
        definition_pages=definition_pages,
    )

    next_definition_id = 1
    page_entry_ids: dict[int, list[str]] = {}

    for page in pages:
        if page.page_number not in definition_pages:
            continue

        page_width = max(page.width, 1.0)
        candidates = [
            element
            for element in page.elements
            if element.type in {"section_header", "paragraph", "list_item", "page_footer", "definition_term"}
            and _looks_short_definition_term(element, page_width)
        ]
        right_candidates = [
            element
            for element in page.elements
            if _definition_text_candidate(element, page_width)
        ]

        strong_pairs: list[tuple[CanonicalElement, CanonicalElement]] = []
        for term in candidates:
            possible = [
                candidate
                for candidate in right_candidates
                if candidate.element_id != term.element_id
                and candidate.bbox[0] >= term.bbox[2] + max(18.0, page_width * 0.045)
                and _same_row(term, candidate)
            ]
            if not possible:
                continue
            paired = min(possible, key=lambda candidate: abs(candidate.bbox[1] - term.bbox[1]))
            strong_pairs.append((term, paired))

        if not strong_pairs:
            continue

        # Terms are grouped by vertical row. The next term starts the next
        # definition entry; every right-column prose block between the two rows
        # belongs to the current entry.
        strong_pairs.sort(key=lambda pair: (pair[0].bbox[1], pair[0].bbox[0]))
        page_entry_ids[page.page_number] = []
        for index, (term, paired) in enumerate(strong_pairs):
            definition_id = f"def-{next_definition_id}"
            next_definition_id += 1
            page_entry_ids[page.page_number].append(definition_id)

            next_y = strong_pairs[index + 1][0].bbox[1] if index + 1 < len(strong_pairs) else float("inf")
            term_y = term.bbox[1]

            term.type = "definition_term"
            term.text = " ".join(term.text.split()).strip()
            term.definition_entry_id = definition_id
            term.heading_level = None
            term.heading_level_source = None
            if not term.role_source.startswith("definition_row_recovery"):
                term.role_source = "definition_list_geometry"

            definition_blocks = [
                candidate
                for candidate in right_candidates
                if candidate.bbox[1] >= term_y - 4.0
                and candidate.bbox[1] < next_y - 4.0
                and candidate.bbox[0] >= page_width * 0.38
            ]
            if paired not in definition_blocks:
                definition_blocks.append(paired)

            for candidate in sorted(definition_blocks, key=lambda item: (item.bbox[1], item.reading_order)):
                candidate.type = "definition_text"
                candidate.text = " ".join(candidate.text.split()).strip()
                candidate.definition_entry_id = definition_id
                candidate.heading_level = None
                candidate.heading_level_source = None
                if not candidate.role_source.startswith("definition_row_recovery"):
                    candidate.role_source = "definition_list_geometry"

    return _reconcile_cross_page_definition_continuations(
        pages=pages,
        definition_pages=definition_pages,
        page_entry_ids=page_entry_ids,
    )


def _build_definition_entries(
    elements: list[CanonicalElement],
    pages: list[StructuredPage],
) -> list[DefinitionEntry]:
    grouped: dict[str, list[CanonicalElement]] = {}
    for element in elements:
        if element.definition_entry_id:
            grouped.setdefault(element.definition_entry_id, []).append(element)

    page_by_number = {page.page_number: page for page in pages}
    entries: list[DefinitionEntry] = []
    for definition_id, members in sorted(
        grouped.items(),
        key=lambda item: min(member.document_order for member in item[1]),
    ):
        ordered = sorted(members, key=lambda item: item.document_order)
        term = next((item for item in ordered if item.type == "definition_term"), None)
        if term is None:
            continue
        definition_parts = [item for item in ordered if item.type == "definition_text"]
        if not definition_parts:
            continue

        start_page = min(item.page_number for item in ordered)
        end_page = max(item.page_number for item in ordered)
        last_part = definition_parts[-1]
        last_page = page_by_number.get(last_part.page_number)
        continues = bool(
            last_page
            and last_part.bbox[3] >= last_page.height * 0.82
            and _text_looks_incomplete(last_part.text)
        )
        definition_text = "\n\n".join(item.text.strip() for item in definition_parts if item.text.strip())
        entries.append(
            DefinitionEntry(
                definition_id=definition_id,
                term=term.text,
                section_id=term.section_id,
                term_element_id=term.element_id,
                source_kind="layout_columns",
                definition_text=definition_text,
                items=_parse_definition_items(definition_text),
                definition_element_ids=[item.element_id for item in definition_parts],
                start_page=start_page,
                end_page=end_page,
                spans_multiple_pages=end_page > start_page,
                continues_to_next_page=continues,
            )
        )

    return entries


def _assign_heading_levels(
    elements: list[CanonicalElement],
    layout_result: dict,
    *,
    title_root_present: bool,
) -> None:
    toc = _toc_items(layout_result)
    unresolved: list[CanonicalElement] = []
    root_offset = 1 if title_root_present else 0

    for element in elements:
        if element.type != "section_header":
            continue

        level = _match_toc_level(element.text, element.page_number, toc)
        if level is not None:
            element.heading_level = min(level + root_offset, 6)
            element.heading_level_source = "pdf_toc"
            continue

        depth = _numbering_depth(element.text)
        if depth is not None:
            element.heading_level = min(depth + root_offset, 6)
            element.heading_level_source = "numbering"
            continue

        unresolved.append(element)

    sizes = sorted(
        {round(float(item.dominant_font_size), 1) for item in unresolved if item.dominant_font_size},
        reverse=True,
    )
    size_rank = {size: min(index + 1 + root_offset, 6) for index, size in enumerate(sizes)}
    for element in unresolved:
        if element.dominant_font_size:
            element.heading_level = size_rank[round(float(element.dominant_font_size), 1)]
            element.heading_level_source = "font_rank"
        else:
            element.heading_level = None
            element.heading_level_source = "unknown"


def _build_sections(elements: list[CanonicalElement]) -> list[SectionRecord]:
    sections: list[SectionRecord] = []
    stack: list[SectionRecord] = []

    for element in elements:
        if element.type != "section_header":
            continue
        section = SectionRecord(
            section_id=f"sec-{len(sections) + 1}",
            title=element.text or f"Untitled section {len(sections) + 1}",
            level=element.heading_level,
            page_number=element.page_number,
            element_id=element.element_id,
            level_source=element.heading_level_source or "unknown",
            kind=("appendix" if APPENDIX_LABEL.match(element.text) else ("question" if _looks_question(element.text) else "section")),
        )

        if section.level is not None:
            while stack and (stack[-1].level is None or stack[-1].level >= section.level):
                stack.pop()
            if stack:
                section.parent_section_id = stack[-1].section_id
            stack.append(section)
        else:
            stack.clear()

        element.section_id = section.section_id
        sections.append(section)

    section_by_element = {section.element_id: section for section in sections}
    section_by_id = {section.section_id: section for section in sections}
    current_section: str | None = None

    for element in elements:
        matched = section_by_element.get(element.element_id)
        if matched:
            current_section = matched.section_id
            continue

        if element.type in {"page_header", "page_footer", "title", "subtitle", "document_metadata"}:
            continue

        element.section_id = current_section
        if current_section is not None:
            section_by_id[current_section].content_element_ids.append(element.element_id)

    return sections



def _refine_footnotes(pages: list[StructuredPage]) -> None:
    """Repair long footnotes that a layout engine labelled as page footers."""
    for page in pages:
        width = max(page.width, 1.0)
        for element in page.elements:
            if element.type != "page_footer":
                continue
            text = " ".join(element.text.split()).strip()
            if not text or text.isdigit() or len(text) < 24:
                continue
            box_width = max(0.0, element.bbox[2] - element.bbox[0])
            marker = bool(FOOTNOTE_MARKER.match(text))
            small_font = element.dominant_font_size is not None and element.dominant_font_size <= 9.5
            if box_width >= width * 0.55 and (marker or small_font):
                element.type = "footnote"
                element.role_source = "footer_to_footnote_geometry"


def _refine_figure_roles(elements: list[CanonicalElement], pages: list[StructuredPage]) -> None:
    """Demote figure-adjacent pseudo-headings before outline construction."""
    for page in pages:
        figures = [element for element in page.elements if element.type == "figure"]
        if not figures:
            continue
        ordered = sorted(page.elements, key=lambda item: item.reading_order)
        for figure in figures:
            previous = [
                element for element in ordered
                if element.reading_order < figure.reading_order
                and figure.bbox[1] - element.bbox[3] <= 95
                and figure.bbox[1] >= element.bbox[3] - 3
            ]
            for element in previous[-3:]:
                text = " ".join(element.text.split()).strip()
                if not text or element.type not in {"section_header", "caption", "paragraph"}:
                    continue
                sentence_like = len(text) > 35 or text.endswith((':', '.', '?'))
                if FIGURE_INTRO.search(text) and sentence_like:
                    if element.type == "section_header" and _numbering_depth(text) is None:
                        element.type = "paragraph"
                        element.heading_level = None
                        element.heading_level_source = None
                    element.role_source = "figure_intro_geometry"
                elif FIGURE_LABEL.search(text):
                    if element.type == "section_header" and _numbering_depth(text) is None:
                        element.type = "caption"
                        element.heading_level = None
                        element.heading_level_source = None
                    element.role_source = "figure_caption_geometry"


def _build_table_definition_entries(
    elements: list[CanonicalElement],
    existing: list[DefinitionEntry],
    pages: list[StructuredPage],
) -> list[DefinitionEntry]:
    definition_pages = _definition_context_pages(elements, pages)
    if not definition_pages:
        return []
    max_id = 0
    for entry in existing:
        match = re.search(r"(\d+)$", entry.definition_id)
        if match:
            max_id = max(max_id, int(match.group(1)))

    output: list[DefinitionEntry] = []
    for element in elements:
        if element.page_number not in definition_pages:
            continue
        rows = _definition_table_rows(element)
        if not rows:
            continue
        for term, definition_text in rows:
            max_id += 1
            output.append(
                DefinitionEntry(
                    definition_id=f"def-{max_id}",
                    term=term,
                    section_id=element.section_id,
                    source_table_element_id=element.element_id,
                    source_kind="table_rows",
                    definition_text=definition_text,
                    items=_parse_definition_items(definition_text),
                    start_page=element.page_number,
                    end_page=element.page_number,
                    spans_multiple_pages=False,
                    continues_to_next_page=False,
                )
            )
    return output


def _build_clause_records(
    elements: list[CanonicalElement],
    sections: list[SectionRecord],
) -> tuple[list[ClauseRecord], list[StructuralRelation]]:
    section_element_by_id = {section.section_id: section.element_id for section in sections}
    records: list[ClauseRecord] = []
    relations: list[StructuralRelation] = []
    current_clause_by_section: dict[str | None, ClauseRecord] = {}

    for element in sorted(elements, key=lambda item: item.document_order):
        if element.type == "clause":
            clause = ClauseRecord(
                clause_id=f"clause-{len(records) + 1}",
                number=element.clause_number or "",
                kind="clause",
                element_id=element.element_id,
                page_number=element.page_number,
                section_id=element.section_id,
            )
            element.clause_id = clause.clause_id
            records.append(clause)
            current_clause_by_section[element.section_id] = clause
            if element.section_id and element.section_id in section_element_by_id:
                relations.append(StructuralRelation(
                    relation_id=f"rel-{len(relations) + 1}",
                    type="belongs_to",
                    source_element_id=element.element_id,
                    target_element_id=section_element_by_id[element.section_id],
                    evidence="clause inherits active section",
                ))
        elif element.type == "subclause":
            parent = current_clause_by_section.get(element.section_id)
            clause = ClauseRecord(
                clause_id=f"clause-{len(records) + 1}",
                number=element.subclause_marker or "",
                kind="subclause",
                element_id=element.element_id,
                page_number=element.page_number,
                section_id=element.section_id,
                parent_clause_id=parent.clause_id if parent else None,
            )
            element.clause_id = clause.clause_id
            element.parent_clause_id = clause.parent_clause_id
            records.append(clause)
            if parent:
                relations.append(StructuralRelation(
                    relation_id=f"rel-{len(relations) + 1}",
                    type="parent_of",
                    source_element_id=parent.element_id,
                    target_element_id=element.element_id,
                    evidence="alphabetic subclause follows active numbered clause",
                ))
    return records, relations


def _build_appendices(
    elements: list[CanonicalElement],
    sections: list[SectionRecord],
    pages: list[StructuredPage],
) -> tuple[list[AppendixRecord], list[StructuralRelation]]:
    """Build appendix containers using document-order boundaries, not whole pages.

    A new appendix can start part-way through a page. Restricting membership by
    document order avoids incorrectly attaching earlier content on that page to
    the appendix.
    """
    section_by_element = {section.element_id: section for section in sections}
    ordered = sorted(elements, key=lambda item: item.document_order)
    labels = [element for element in ordered if element.type == "section_header" and APPENDIX_LABEL.match(element.text)]
    if not labels:
        return [], []

    max_page = max((page.page_number for page in pages), default=1)
    records: list[AppendixRecord] = []
    relations: list[StructuralRelation] = []
    for index, label in enumerate(labels):
        match = APPENDIX_LABEL.match(label.text)
        assert match is not None
        appendix_id = f"appendix-{match.group(1).lower()}"
        next_label_order = labels[index + 1].document_order if index + 1 < len(labels) else float("inf")
        next_label_page = labels[index + 1].page_number if index + 1 < len(labels) else None

        title_element = next((
            item for item in ordered
            if item.document_order > label.document_order
            and item.document_order < next_label_order
            and item.page_number == label.page_number
            and item.type in {"section_header", "subtitle", "title"}
            and not APPENDIX_LABEL.match(item.text)
        ), None)

        end_page = (next_label_page - 1) if next_label_page is not None else max_page
        record = AppendixRecord(
            appendix_id=appendix_id,
            label=" ".join(label.text.split()),
            label_element_id=label.element_id,
            title=title_element.text if title_element else None,
            title_element_id=title_element.element_id if title_element else None,
            start_page=label.page_number,
            end_page=max(label.page_number, end_page),
        )
        records.append(record)

        section = section_by_element.get(label.element_id)
        if section is not None:
            section.kind = "appendix"

        for item in ordered:
            if item.document_order < label.document_order or item.document_order >= next_label_order:
                continue
            item.appendix_id = appendix_id

        if title_element is not None:
            relations.append(StructuralRelation(
                relation_id=f"rel-appendix-{len(relations) + 1}",
                type="belongs_to",
                source_element_id=title_element.element_id,
                target_element_id=label.element_id,
                evidence="appendix title immediately follows appendix label",
            ))

    return records, relations

def _table_columns_compatible(a: CanonicalElement, b: CanonicalElement, page_width: float) -> bool:
    if a.table is None or b.table is None or a.table.col_count != b.table.col_count:
        return False
    tolerance = max(18.0, page_width * 0.055)
    return abs(a.bbox[0] - b.bbox[0]) <= tolerance and abs(a.bbox[2] - b.bbox[2]) <= tolerance


def _table_context_compatible(a: CanonicalElement, b: CanonicalElement) -> bool:
    # If either fragment has explicit appendix context, both must agree.
    if (a.appendix_id or b.appendix_id) and a.appendix_id != b.appendix_id:
        return False
    # Same rule for explicit section context. A missing section is tolerated
    # because continuation pages can start before the first repeated heading.
    if a.section_id and b.section_id and a.section_id != b.section_id:
        return False
    return True


def _normalize_table_row(row: list[str | None]) -> list[str]:
    return [" ".join(str(value or "").split()).casefold() for value in row]


def _merge_table_cells(fragments: list[CanonicalElement]) -> list[list[str | None]]:
    rows: list[list[str | None]] = []
    header: list[str | None] | None = None
    for index, fragment in enumerate(fragments):
        if fragment.table is None:
            continue
        fragment_rows = [list(row) for row in fragment.table.cells]
        if not fragment_rows:
            continue
        if index == 0:
            rows.extend(fragment_rows)
            header = fragment_rows[0]
            continue
        # Many multipage tables repeat the header on every page. Keep it once.
        if header is not None and fragment_rows and _normalize_table_row(fragment_rows[0]) == _normalize_table_row(header):
            fragment_rows = fragment_rows[1:]
        rows.extend(fragment_rows)
    return rows


def _has_substantive_content_before_table(page: StructuredPage, candidate: CanonicalElement) -> bool:
    """A continuation fragment should be the first substantive body block.

    Page headers, footers and empty metadata do not count. A paragraph, figure,
    clause, list item or another table before the candidate is strong evidence
    that this is a new table instead of a continuation.
    """
    ignored = {"page_header", "page_footer", "document_metadata"}
    for item in page.elements:
        if item.element_id == candidate.element_id:
            continue
        if item.bbox[1] >= candidate.bbox[1]:
            continue
        if item.type in ignored or not item.text.strip():
            continue
        return True
    return False


def _build_logical_tables(
    pages: list[StructuredPage],
) -> tuple[list[LogicalTable], list[StructuralRelation]]:
    page_by_number = {page.page_number: page for page in pages}
    fragments = sorted(
        [element for page in pages for element in page.elements if element.type == "table" and element.table is not None],
        key=lambda item: item.document_order,
    )
    used: set[str] = set()
    logical: list[LogicalTable] = []
    relations: list[StructuralRelation] = []

    for fragment in fragments:
        if fragment.element_id in used:
            continue
        chain = [fragment]
        used.add(fragment.element_id)
        current = fragment
        while True:
            current_page = page_by_number.get(current.page_number)
            next_page = page_by_number.get(current.page_number + 1)
            if current_page is None or next_page is None:
                break
            next_tables = [
                item for item in next_page.elements
                if item.type == "table" and item.table is not None and item.element_id not in used
            ]
            if not next_tables:
                break
            candidate = min(next_tables, key=lambda item: item.bbox[1])

            # Strong continuation evidence: current fragment approaches the
            # bottom edge, next fragment begins near the top, same column
            # geometry, and no intervening semantic content / context change.
            if current.bbox[3] < current_page.height * 0.72 or candidate.bbox[1] > next_page.height * 0.30:
                break
            if _has_substantive_content_before_table(next_page, candidate):
                break
            if not _table_columns_compatible(current, candidate, max(current_page.width, next_page.width, 1.0)):
                break
            if not _table_context_compatible(current, candidate):
                break

            chain.append(candidate)
            used.add(candidate.element_id)
            current = candidate

        logical_id = f"table-{len(logical) + 1}"
        for item in chain:
            item.logical_table_id = logical_id
        cells = _merge_table_cells(chain)
        logical.append(LogicalTable(
            logical_table_id=logical_id,
            fragment_element_ids=[item.element_id for item in chain],
            start_page=chain[0].page_number,
            end_page=chain[-1].page_number,
            spans_multiple_pages=len(chain) > 1,
            row_count=len(cells),
            col_count=max((len(row) for row in cells), default=chain[0].table.col_count if chain[0].table else 0),
            cells=cells,
            section_id=chain[0].section_id,
            merge_source="cross_page_geometry" if len(chain) > 1 else "single_fragment",
        ))
        for left, right in zip(chain, chain[1:]):
            relations.append(StructuralRelation(
                relation_id=f"rel-table-{len(relations) + 1}",
                type="continues",
                source_element_id=left.element_id,
                target_element_id=right.element_id,
                evidence="adjacent-page tables share column count, x-boundaries, semantic context, and page-edge geometry",
            ))
    return logical, relations

def _build_figures_and_relations(
    pages: list[StructuredPage],
) -> tuple[list[FigureRecord], list[StructuralRelation]]:
    figures: list[FigureRecord] = []
    relations: list[StructuralRelation] = []
    for page in pages:
        ordered = sorted(page.elements, key=lambda item: item.reading_order)
        for figure in [item for item in ordered if item.type == "figure"]:
            figure_id = f"figure-{len(figures) + 1}"
            figure.figure_id = figure_id
            intro_ids: list[str] = []
            caption_ids: list[str] = []
            explanation_ids: list[str] = []
            source_ids: list[str] = []

            before = [item for item in ordered if item.reading_order < figure.reading_order and figure.bbox[1] - item.bbox[3] <= 110]
            for item in before[-3:]:
                text = " ".join(item.text.split()).strip()
                if not text:
                    continue
                sentence_like = len(text) > 35 or text.endswith((':', '.', '?'))
                if item.role_source == "figure_intro_geometry" or (FIGURE_INTRO.search(text) and sentence_like):
                    intro_ids.append(item.element_id)
                    relations.append(StructuralRelation(
                        relation_id=f"rel-figure-{len(relations) + 1}", type="introduces",
                        source_element_id=item.element_id, target_element_id=figure.element_id,
                        evidence="introductory figure language and close vertical proximity",
                    ))
                elif item.type == "caption" or (FIGURE_LABEL.search(text) and len(text) <= 140):
                    caption_ids.append(item.element_id)
                    relations.append(StructuralRelation(
                        relation_id=f"rel-figure-{len(relations) + 1}", type="caption_of",
                        source_element_id=item.element_id, target_element_id=figure.element_id,
                        evidence="caption/illustration label immediately precedes figure",
                    ))

            after = [item for item in ordered if item.reading_order > figure.reading_order]
            for item in after:
                if item.bbox[1] - figure.bbox[3] > 420:
                    break
                if item.type in {"figure", "table"}:
                    break
                text = " ".join(item.text.split()).strip()
                if not text or item.type in {"page_footer", "page_header"}:
                    continue
                if SOURCE_HINT.search(text):
                    source_ids.append(item.element_id)
                    relations.append(StructuralRelation(
                        relation_id=f"rel-figure-{len(relations) + 1}", type="source_for",
                        source_element_id=item.element_id, target_element_id=figure.element_id,
                        evidence="source/reference language follows figure",
                    ))
                elif item.type in {"section_header", "clause", "subclause"}:
                    # A new numbered structural unit starts normal document
                    # content; it should not be swallowed as figure explanation.
                    break
                elif item.type in {"paragraph", "list_item"}:
                    explanation_ids.append(item.element_id)
                    relations.append(StructuralRelation(
                        relation_id=f"rel-figure-{len(relations) + 1}", type="explains",
                        source_element_id=item.element_id, target_element_id=figure.element_id,
                        evidence="explanatory body content follows figure before next structural block",
                    ))

            figures.append(FigureRecord(
                figure_id=figure_id,
                element_id=figure.element_id,
                page_number=figure.page_number,
                section_id=figure.section_id,
                intro_element_ids=intro_ids,
                caption_element_ids=caption_ids,
                explanation_element_ids=explanation_ids,
                source_element_ids=source_ids,
            ))
    return figures, relations


def _element_body_text(element: CanonicalElement) -> str:
    if element.type not in CONTENT_TYPES:
        return ""
    if element.type == "table" and element.table and element.table.markdown:
        return element.table.markdown.strip()
    return element.text.strip()


def build_canonical_document(
    *,
    record: DocumentRecord,
    extraction: DocumentExtraction,
    layout_artifact: dict,
) -> StructuredDocument:
    layout_result = layout_artifact.get("result") or {}
    layout_pages = layout_result.get("pages") or []
    extraction_by_page = {page.page_number: page for page in extraction.pages}

    elements: list[CanonicalElement] = []
    pages: list[StructuredPage] = []
    document_order = 0
    warnings: list[str] = []

    if record.classification.pdf_type == "scanned":
        warnings.append(
            "Stage 4 layout analysis ran with OCR disabled. Scanned pages may contain visual regions but little or no structured text."
        )
    elif record.classification.pdf_type == "mixed":
        warnings.append(
            "Stage 4 layout analysis ran with OCR disabled. Image-only regions in mixed pages may remain without text."
        )

    for page_index, layout_page in enumerate(layout_pages, start=1):
        page_number = int(layout_page.get("page_number") or page_index)
        raw_page = extraction_by_page.get(page_number)
        if raw_page is None:
            warnings.append(f"Layout output contains page {page_number}, but Stage 3 extraction does not.")
            continue

        page_elements: list[CanonicalElement] = []
        for reading_order, box in enumerate(layout_page.get("boxes") or []):
            boxclass = str(box.get("boxclass") or "unknown")
            canonical_type = BOX_TYPE_MAP.get(boxclass, "unknown")
            bbox = _bbox_from_box(box)
            element = CanonicalElement(
                element_id=f"p{page_number}-e{reading_order + 1}",
                type=canonical_type,
                page_number=page_number,
                reading_order=reading_order,
                document_order=document_order,
                bbox=bbox,
                text=_box_text(box),
                dominant_font_size=_dominant_font_size(raw_page, bbox),
                role_source="layout",
                table=_canonical_table(box) if canonical_type == "table" else None,
                source=_source_trace(raw_page, bbox, reading_order, boxclass),
            )
            page_elements.append(element)
            elements.append(element)
            document_order += 1

        pages.append(
            StructuredPage(
                page_number=page_number,
                width=round(float(layout_page.get("width") or raw_page.width), 3),
                height=round(float(layout_page.get("height") or raw_page.height), 3),
                elements=page_elements,
                body_text="",
            )
        )

    title_element, subtitle_element, metadata_elements = _refine_document_roles(elements, pages)
    _normalize_structural_elements(elements)
    _refine_figure_roles(elements, pages)
    _assign_heading_levels(
        elements,
        layout_result,
        title_root_present=title_element is not None,
    )
    _refine_numbered_clauses(elements)
    definition_relations = _refine_definition_lists(elements, pages, extraction_by_page)
    _refine_footnotes(pages)

    sections = _build_sections(elements)
    definitions = _build_definition_entries(elements, pages)
    definitions.extend(_build_table_definition_entries(elements, definitions, pages))
    clauses, clause_relations = _build_clause_records(elements, sections)
    appendices, appendix_relations = _build_appendices(elements, sections, pages)
    logical_tables, table_relations = _build_logical_tables(pages)
    figures, figure_relations = _build_figures_and_relations(pages)
    relationships = definition_relations + clause_relations + appendix_relations + table_relations + figure_relations

    for page in pages:
        page.body_text = "\n\n".join(
            text for text in (_element_body_text(element) for element in page.elements) if text
        )

    body_text = "\n\n".join(page.body_text for page in pages if page.body_text)
    counts = Counter(element.type for element in elements)

    metadata = layout_result.get("metadata") or {}
    metadata_title = str(metadata.get("title") or "").strip() if isinstance(metadata, dict) else ""
    if title_element and title_element.text.strip():
        title = title_element.text.strip()
        title_source = title_element.role_source
    elif metadata_title:
        title = metadata_title
        title_source = "pdf_metadata"
    else:
        title = Path(record.original_filename).stem
        title_source = "filename"

    subtitle = subtitle_element.text.strip() if subtitle_element and subtitle_element.text.strip() else None
    subtitle_source = subtitle_element.role_source if subtitle_element is not None else None

    engine = layout_artifact.get("engine") or {}
    return StructuredDocument(
        document_id=record.document_id,
        source_filename=record.original_filename,
        source_sha256=record.sha256,
        source_extraction_schema_version=extraction.schema_version,
        layout_engine=LayoutEngineInfo(
            name=str(engine.get("name") or "PyMuPDF4LLM Layout"),
            version=str(engine.get("version") or "unknown"),
            settings=engine.get("settings") or {},
        ),
        title=title,
        title_source=title_source,
        subtitle=subtitle,
        subtitle_source=subtitle_source,
        outline_root_element_id=title_element.element_id if title_element else None,
        metadata_element_ids=[element.element_id for element in metadata_elements],
        summary=StructureSummary(
            page_count=len(pages),
            element_count=len(elements),
            body_text_char_count=len(body_text),
            section_count=len(sections),
            definition_count=len(definitions),
            clause_count=len(clauses),
            appendix_count=len(appendices),
            logical_table_count=len(logical_tables),
            figure_count=len(figures),
            relation_count=len(relationships),
            element_counts=dict(sorted(counts.items())),
        ),
        sections=sections,
        definitions=definitions,
        clauses=clauses,
        appendices=appendices,
        tables=logical_tables,
        figures=figures,
        relationships=relationships,
        pages=pages,
        body_text=body_text,
        warnings=warnings,
        structured_at=datetime.now(timezone.utc),
    )
