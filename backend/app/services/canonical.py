from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re

from app.services.spans import iter_page_spans
from app.services.semantic import calibrate_hierarchy_confidence, continuation_boundary_reason, reconcile_same_page_semantic_continuity, resolve_appendix_labels, resolve_appendix_title_scopes, resolve_heading_scopes, resolve_structural_semantics, validate_semantic_structure
from app.services.semantic.classifier import backfill_classification

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
    "group_header",
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
    r"^\s*(?:(\d+(?:\s*[A-Z])?\.\d+(?:\.\d+){0,4})(?=\s|[A-Za-z])|(\d+)[.)](?=\s|[A-Za-z]))\s*",
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
MAJOR_OUTLINE_LABEL = re.compile(r"^\s*(?:PART|CHAPTER|BOOK|DIVISION)\s+[A-Z0-9IVXLC]+(?:\s*[:.-]|\s+)", re.IGNORECASE)
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
DEFINITION_ITEM_PREFIX = re.compile(
    r"^\s*(\((?:[A-Za-z]|\d{1,2}|[ivxlcdmIVXLCDM]{1,6})\)|(?:\d{1,2}|[A-Za-z])[.)])\s*"
)
DEFINITION_ITEM_ANYWHERE = re.compile(
    r"(?:^|\s)(\((?:[A-Za-z]|\d{1,2}|[ivxlcdmIVXLCDM]{1,6})\)|(?:\d{1,2}|[A-Za-z])[.)])\s*"
)


@dataclass(frozen=True)
class OpenBlockState:
    """Reusable state for conservative cross-page reconciliation.

    ``kind`` is semantic (definition, clause, list, paragraph, table), while
    ``expected_column`` is the horizontal region that a continuation is
    expected to occupy on the following page.  The state intentionally carries
    no document-specific vocabulary.
    """

    kind: str
    source_element_id: str
    page_number: int
    expected_column: list[float]
    context_id: str | None = None
    allow_enumerated_items: bool = False


@dataclass(frozen=True)
class HierarchyMarker:
    """Normalized marker metadata used by the cross-page hierarchy engine.

    A marker may have two plausible ordinals (for example ``(i)`` can be the
    ninth alphabetic item or the first roman numeral).  Keeping both candidates
    lets geometry and the neighbouring marker decide the relationship instead
    of hard-coding one legal-document numbering convention.
    """

    raw: str
    style: str
    ordinals: tuple[int, ...]


BULLET_PREFIX = re.compile(r"^\s*([•▪◦●○■□‣⁃])\s+")
PAREN_MARKER_PREFIX = re.compile(r"^\s*\((\d{1,3}[A-Za-z]?|[A-Za-z]|[ivxlcdmIVXLCDM]{1,8})\)\s*")
PLAIN_MARKER_PREFIX = re.compile(r"^\s*(\d{1,3}[A-Za-z]?|[A-Za-z]|[ivxlcdmIVXLCDM]{1,8})[.)]\s+")


def _roman_value(token: str) -> int | None:
    token = token.upper()
    if not token or any(char not in "IVXLCDM" for char in token):
        return None
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    previous = 0
    for char in reversed(token):
        value = values[char]
        if value < previous:
            total -= value
        else:
            total += value
            previous = value
    # Reject malformed roman strings by round-tripping a bounded canonical form.
    if total <= 0 or total > 3999:
        return None
    return total


def _marker_ordinals(token: str) -> tuple[int, ...]:
    if token.isdigit():
        return (int(token),)
    match = re.fullmatch(r"(\d{1,3})([A-Za-z])", token)
    if match:
        return (int(match.group(1)) * 100 + (ord(match.group(2).lower()) - 96),)
    values: list[int] = []
    if len(token) == 1 and token.isalpha():
        values.append(ord(token.lower()) - 96)
    roman = _roman_value(token)
    if roman is not None and roman not in values:
        values.append(roman)
    return tuple(value for value in values if value > 0)


def _hierarchy_marker(text: str) -> HierarchyMarker | None:
    normalized = " ".join(text.split()).strip()
    bullet = BULLET_PREFIX.match(normalized)
    if bullet:
        return HierarchyMarker(raw=bullet.group(1), style="bullet", ordinals=())

    parenthesized = PAREN_MARKER_PREFIX.match(normalized)
    if parenthesized:
        token = parenthesized.group(1)
        if token.isdigit():
            style = "paren_numeric"
        elif re.fullmatch(r"\d+[A-Za-z]", token):
            style = "paren_numeric_alpha"
        elif len(token) == 1 and token.isalpha():
            style = "paren_alpha_or_roman"
        else:
            style = "paren_roman"
        return HierarchyMarker(raw=f"({token})", style=style, ordinals=_marker_ordinals(token))

    plain = PLAIN_MARKER_PREFIX.match(normalized)
    if plain:
        token = plain.group(1)
        if token.isdigit():
            style = "plain_numeric"
        elif re.fullmatch(r"\d+[A-Za-z]", token):
            style = "plain_numeric_alpha"
        elif len(token) == 1 and token.isalpha():
            style = "plain_alpha_or_roman"
        else:
            style = "plain_roman"
        return HierarchyMarker(raw=plain.group(0).strip(), style=style, ordinals=_marker_ordinals(token))
    return None


def _marker_sequence_relation(
    source: CanonicalElement,
    candidate: CanonicalElement,
    page_width: float,
) -> tuple[str | None, int, list[str]]:
    """Return a generic sibling/child relationship score for list markers."""
    left = _hierarchy_marker(source.text)
    right = _hierarchy_marker(candidate.text)
    if left is None or right is None:
        return None, 0, []

    evidence: list[str] = []
    indent_delta = candidate.bbox[0] - source.bbox[0]
    indent_threshold = max(12.0, page_width * 0.018)

    if left.style == "bullet" and right.style == "bullet":
        if abs(indent_delta) <= indent_threshold * 1.5:
            return "sibling", 4, ["bullet marker continues at the same indentation"]
        if indent_delta > indent_threshold:
            return "child", 3, ["bullet marker begins at a deeper indentation"]

    same_style = left.style == right.style
    sequential = any(r == l + 1 for l in left.ordinals for r in right.ordinals)
    if same_style and sequential:
        evidence.append(f"marker sequence advances from {left.raw} to {right.raw}")
        if abs(indent_delta) <= indent_threshold * 1.7:
            return "sibling", 5, evidence
        if indent_delta > indent_threshold:
            evidence.append("next marker is also more deeply indented")
            return "child", 5, evidence

    # A new marker family starting at ordinal 1 at a deeper indentation is a
    # strong generic signal for a nested child list, e.g. (b) -> (i).
    if indent_delta > indent_threshold and 1 in right.ordinals:
        evidence.append(f"{right.raw} starts a new marker family at a deeper indentation")
        return "child", 4, evidence

    # When both markers are ordered and the next ordinal increases, preserve a
    # weaker sibling signal. This handles document conventions such as (20) ->
    # (21) even when the exact vendor type changes between pages.
    if same_style and left.ordinals and right.ordinals and min(right.ordinals) > min(left.ordinals):
        evidence.append(f"marker order increases from {left.raw} to {right.raw}")
        return "sibling", 2, evidence

    return None, 0, []


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


TOC_ENTRY_MARKER = re.compile(r"^\s*\d+[A-Za-z]?(?:\.\d+)*\.?\s*$")
TOC_PAGE_REFERENCE = re.compile(r"^\s*\d{1,4}\s*$")
TOC_CONTEXT_HEADING = re.compile(
    r"^(?:table\s+of\s+)?contents(?:\s+\(?continued\)?)?$",
    re.IGNORECASE,
)


def _cell_lines(value: str | None) -> list[str]:
    if value is None:
        return []
    return [line.strip() for line in str(value).splitlines() if line.strip()]


def _uppercase_heading_like(value: str) -> bool:
    letters = [char for char in value if char.isalpha()]
    if len(letters) < 4:
        return False
    uppercase = sum(char.isupper() for char in letters)
    return uppercase / len(letters) >= 0.8


def _page_has_explicit_toc_context(layout_page: dict) -> bool:
    """Return True only when the page explicitly declares TOC context.

    The canonical TOC row repair is intentionally gated by a visible page-level
    heading such as ``CONTENTS`` or ``TABLE OF CONTENTS`` (optionally marked as
    continued). This prevents a merely TOC-shaped 3-column table elsewhere in a
    document from being rewritten.
    """
    heading_boxclasses = {"title", "section-header", "page-header"}
    for box in layout_page.get("boxes") or []:
        boxclass = str(box.get("boxclass") or "").casefold()
        if boxclass not in heading_boxclasses:
            continue
        text = " ".join(_box_text(box).split()).strip()
        if text and TOC_CONTEXT_HEADING.fullmatch(text):
            return True
    return False


def _looks_like_toc_table(cells: list[list[str | None]]) -> bool:
    """Return True for a stable number/title/page table-of-contents pattern.

    This is deliberately conservative.  It does not depend on document-specific
    words such as ``PART``; instead it looks for repeated numbered entries whose
    final column is a page reference.
    """
    if len(cells) < 4 or max((len(row) for row in cells), default=0) != 3:
        return False

    toc_entry_rows = 0
    for row in cells:
        if len(row) != 3:
            continue
        left_lines = _cell_lines(row[0])
        right_lines = _cell_lines(row[2])
        if not left_lines or len(right_lines) != 1:
            continue
        if TOC_ENTRY_MARKER.fullmatch(left_lines[-1]) and TOC_PAGE_REFERENCE.fullmatch(right_lines[0]):
            toc_entry_rows += 1
    return toc_entry_rows >= 3


def _repair_merged_toc_rows(cells: list[list[str | None]]) -> tuple[list[list[str | None]], bool]:
    """Split a TOC heading accidentally merged with the following entry.

    PyMuPDF4LLM can occasionally emit a row such as::

        ["PART\n7", "II: ...\nRisk-Based Approach Application", "25"]

    even though the heading and numbered entry occupy separate visual y-bands.
    A repair is only applied when the surrounding table already behaves like a
    3-column number/title/page TOC and the embedded first line looks like an
    uppercase heading while the second left-column line is a numbered entry.
    Multi-line titles such as a wrapped ``7.6`` entry are intentionally left
    untouched because their first column contains only one marker.
    """
    if not _looks_like_toc_table(cells):
        return cells, False

    repaired: list[list[str | None]] = []
    changed = False
    for row in cells:
        if len(row) != 3:
            repaired.append(row)
            continue

        left_lines = _cell_lines(row[0])
        middle_lines = _cell_lines(row[1])
        right_lines = _cell_lines(row[2])
        should_split = (
            len(left_lines) >= 2
            and len(middle_lines) >= 2
            and len(right_lines) == 1
            and TOC_PAGE_REFERENCE.fullmatch(right_lines[0]) is not None
            and TOC_ENTRY_MARKER.fullmatch(left_lines[-1]) is not None
            and TOC_ENTRY_MARKER.fullmatch(left_lines[0]) is None
            and _uppercase_heading_like(middle_lines[0])
        )
        if not should_split:
            repaired.append(row)
            continue

        header_row: list[str | None] = [left_lines[0], middle_lines[0], ""]
        entry_row: list[str | None] = [
            "\n".join(left_lines[1:]),
            "\n".join(middle_lines[1:]),
            right_lines[0],
        ]
        repaired.extend([header_row, entry_row])
        changed = True

    return repaired, changed


def _table_cells_markdown(cells: list[list[str | None]]) -> str | None:
    if not cells:
        return None

    def render(cell: str | None) -> str:
        value = str(cell or "").replace("|", "\\|")
        return "<br>".join(line.strip() for line in value.splitlines())

    width = max((len(row) for row in cells), default=0)
    padded = [list(row) + [None] * (width - len(row)) for row in cells]
    lines = ["|" + "|".join(render(cell) for cell in row) + "|" for row in padded]
    if width:
        lines.insert(1, "|" + "|".join("---" for _ in range(width)) + "|")
    return "\n".join(lines) + "\n"


def _table_cells_text(cells: list[list[str | None]]) -> str:
    rows = []
    for row in cells:
        rows.append("\t".join("" if cell is None else str(cell).strip() for cell in row).rstrip())
    return "\n".join(row for row in rows if row).strip()


def _canonical_table(box: dict, *, allow_toc_row_repair: bool = False) -> CanonicalTable | None:
    table = box.get("table")
    if not isinstance(table, dict):
        return None
    cells = table.get("extract") or []
    normalized_cells = [[None if cell is None else str(cell) for cell in row] for row in cells]
    if allow_toc_row_repair:
        repaired_cells, repaired = _repair_merged_toc_rows(normalized_cells)
    else:
        repaired_cells, repaired = normalized_cells, False
    return CanonicalTable(
        row_count=len(repaired_cells) if repaired else int(table.get("row_count") or len(repaired_cells)),
        col_count=max((len(row) for row in repaired_cells), default=int(table.get("col_count") or 0)),
        cells=repaired_cells,
        markdown=_table_cells_markdown(repaired_cells) if repaired else table.get("markdown"),
    )


def _repair_canonical_toc_table(element: CanonicalElement) -> bool:
    """Apply the conservative TOC row repair to one canonical table fragment.

    The helper updates every derived representation together so downstream
    logical-table merging, page body text, and the inspector all observe the
    same repaired rows.
    """
    if element.type != "table" or element.table is None:
        return False

    repaired_cells, repaired = _repair_merged_toc_rows(element.table.cells)
    if not repaired:
        return False

    element.table.cells = repaired_cells
    element.table.row_count = len(repaired_cells)
    element.table.col_count = max((len(row) for row in repaired_cells), default=element.table.col_count)
    element.table.markdown = _table_cells_markdown(repaired_cells)
    element.text = _table_cells_text(repaired_cells)
    return True


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
    value = match.group(1) or match.group(2)
    return re.sub(r"\s+", "", value) if value else None


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


TERM_CONTINUATION_PAREN = re.compile(r"^\s*\([^()]{1,48}\)\s*$")


def _looks_multiline_term_continuation(
    previous: CanonicalElement,
    current: CanonicalElement,
    page_width: float,
) -> bool:
    """Return True when two left-column fragments are likely one wrapped term.

    The rule is deliberately vocabulary-free.  It relies on a tight vertical
    gap, matching left-column alignment and a continuation-like second line
    (for example a parenthesized acronym or lower-case wrapped text).  A very
    tight gap is also accepted when the combined label still looks like a
    definition term.  This covers terms split by layout segmentation while
    avoiding normal glossary rows that are merely adjacent vertically.
    """
    if not previous.text.strip() or not current.text.strip() or page_width <= 0:
        return False
    if not _looks_definition_term_text(previous.text) or not _looks_definition_term_text(current.text):
        return False

    prev_h = max(1.0, previous.bbox[3] - previous.bbox[1])
    curr_h = max(1.0, current.bbox[3] - current.bbox[1])
    gap = current.bbox[1] - previous.bbox[3]
    max_gap = max(4.0, min(14.0, min(prev_h, curr_h) * 0.85))
    if gap < -3.0 or gap > max_gap:
        return False

    left_tolerance = max(8.0, page_width * 0.018)
    aligned_left = abs(previous.bbox[0] - current.bbox[0]) <= left_tolerance
    overlap = _horizontal_overlap_ratio(previous.bbox, current.bbox)
    if not aligned_left and overlap < 0.65:
        return False

    current_text = " ".join(current.text.split()).strip()
    previous_text = " ".join(previous.text.split()).strip()
    combined = f"{previous_text} {current_text}".strip()
    if not _looks_definition_term_text(combined):
        return False

    strong_continuation_signal = bool(
        TERM_CONTINUATION_PAREN.match(current_text)
        or previous_text.endswith(("-", "/", "&"))
    )
    # A near-zero inter-line gap is strong geometric evidence even when the
    # wrapped second line begins with a capital or lower-case word.  Lower-case
    # text by itself is intentionally *not* enough: glossary terms are often
    # lower-case and may be closely spaced on dense pages.
    very_tight = gap <= max(2.5, min(prev_h, curr_h) * 0.25)
    return strong_continuation_signal or very_tight


def _merge_source_trace(primary: CanonicalElement, secondary: CanonicalElement) -> None:
    """Preserve Stage-3 provenance when two canonical fragments are merged."""
    primary.source.stage3_block_ids = list(dict.fromkeys(
        primary.source.stage3_block_ids + secondary.source.stage3_block_ids
    ))
    primary.source.stage3_line_ids = list(dict.fromkeys(
        primary.source.stage3_line_ids + secondary.source.stage3_line_ids
    ))
    primary.source.stage3_span_ids = list(dict.fromkeys(
        primary.source.stage3_span_ids + secondary.source.stage3_span_ids
    ))
    primary.source.stage3_table_ids = list(dict.fromkeys(
        primary.source.stage3_table_ids + secondary.source.stage3_table_ids
    ))


def _consolidate_multiline_definition_terms(
    *,
    elements: list[CanonicalElement],
    pages: list[StructuredPage],
    definition_pages: set[int],
) -> int:
    """Merge wrapped left-column term fragments before definition pairing.

    This is a canonical repair, not a parser-specific rule.  It works whether
    the layout engine emitted the term as two text boxes, two list-item boxes,
    or a mixture of recovered and vendor elements.  Only tightly stacked,
    aligned, term-like fragments are merged.
    """
    merged_count = 0
    allowed = {"paragraph", "list_item", "section_header", "page_footer", "definition_term"}

    for page in pages:
        if page.page_number not in definition_pages:
            continue
        width = max(page.width, 1.0)
        left = [
            item for item in page.elements
            if item.definition_entry_id is None
            and item.type in allowed
            and not item.role_source.startswith("definition_")
            and _looks_short_definition_term(item, width)
            and not _looks_definition_context(item.text)
        ]
        if len(left) < 2:
            continue

        ordered = sorted(left, key=lambda item: (item.bbox[1], item.bbox[0], item.reading_order))
        remove_ids: set[str] = set()
        index = 0
        while index < len(ordered) - 1:
            primary = ordered[index]
            if primary.element_id in remove_ids:
                index += 1
                continue
            secondary = ordered[index + 1]
            if secondary.element_id in remove_ids:
                index += 1
                continue

            if not _looks_multiline_term_continuation(primary, secondary, width):
                index += 1
                continue

            primary.text = " ".join(f"{primary.text} {secondary.text}".split()).strip()
            combined_bbox = _union_bbox([primary.bbox, secondary.bbox])
            if combined_bbox is not None:
                primary.bbox = combined_bbox
            primary.type = "definition_term"
            primary.heading_level = None
            primary.heading_level_source = None
            primary.role_source = "definition_multiline_term_consolidation"
            _merge_source_trace(primary, secondary)
            remove_ids.add(secondary.element_id)
            merged_count += 1

            # Keep the merged primary in place so three-line terms can be
            # consolidated iteratively with the next fragment.
            ordered[index] = primary
            ordered.pop(index + 1)

        if remove_ids:
            page.elements = [item for item in page.elements if item.element_id not in remove_ids]

    if merged_count:
        _reindex_canonical_elements(elements, pages)
    return merged_count


def _normalized_match_text(text: str) -> str:
    """Normalize text only for provenance / geometry matching."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text.casefold()).split())


def _stage3_block_ids_for_bbox(raw_page, bbox: list[float]) -> list[str]:
    ids: list[str] = []
    for block in raw_page.blocks:
        if getattr(block, "type", None) != "text":
            continue
        if _intersection(block.bbox, bbox) > 0:
            ids.append(block.block_id)
    return ids


def _stage3_left_line_fragments(raw_page, split_x: float) -> list[dict]:
    """Return left-column Stage-3 line fragments with block provenance.

    This intentionally works below the vendor layout layer.  It lets Stage 4
    recover a wrapped term line that the layout engine omitted or absorbed into
    a neighbouring region.
    """
    fragments: list[dict] = []
    for block in raw_page.blocks:
        if getattr(block, "type", None) != "text":
            continue
        for line in block.lines:
            spans = [
                span for span in line.spans
                if span.text.strip() and ((span.bbox[0] + span.bbox[2]) / 2.0) < split_x
            ]
            if not spans:
                continue
            text = " ".join(span.text.strip() for span in spans if span.text.strip()).strip()
            bbox = _union_bbox([list(span.bbox) for span in spans])
            if not text or bbox is None:
                continue
            fragments.append({
                "text": text,
                "bbox": bbox,
                "block_id": block.block_id,
            })
    return sorted(fragments, key=lambda item: (item["bbox"][1], item["bbox"][0]))


def _raw_fragment_matches_element(fragment: dict, element: CanonicalElement) -> bool:
    left = _normalized_match_text(fragment["text"])
    right = _normalized_match_text(element.text)
    if not left or not right:
        return False
    if left == right:
        return True
    # A layout engine may preserve / drop punctuation around an acronym.
    if left in right or right in left:
        return _vertical_overlap_ratio(fragment["bbox"], element.bbox) >= 0.45
    return False


def _raw_term_fragment_continuation(
    first: dict,
    second: dict,
    *,
    page_width: float,
) -> bool:
    """Return True for a high-confidence wrapped definition-term line pair.

    We deliberately require stronger evidence than simple vertical proximity.
    The most common safe signal is a parenthesized continuation such as an
    acronym, but connector endings and same-block, near-zero-gap wraps are also
    supported.  No vocabulary or document-specific term names are used.
    """
    first_text = " ".join(first["text"].split()).strip()
    second_text = " ".join(second["text"].split()).strip()
    combined = f"{first_text} {second_text}".strip()
    if not _looks_definition_term_text(first_text) or not _looks_definition_term_text(second_text):
        return False
    if not _looks_definition_term_text(combined):
        return False

    first_h = max(1.0, first["bbox"][3] - first["bbox"][1])
    second_h = max(1.0, second["bbox"][3] - second["bbox"][1])
    gap = second["bbox"][1] - first["bbox"][3]
    max_gap = max(4.0, min(14.0, min(first_h, second_h) * 0.9))
    if gap < -3.0 or gap > max_gap:
        return False

    left_tolerance = max(8.0, page_width * 0.018)
    aligned = abs(first["bbox"][0] - second["bbox"][0]) <= left_tolerance
    overlap = _horizontal_overlap_ratio(first["bbox"], second["bbox"])
    if not aligned and overlap < 0.6:
        return False

    parenthetical = bool(TERM_CONTINUATION_PAREN.match(second_text))
    connector = first_text.endswith(("-", "/", "&"))
    same_block = first.get("block_id") == second.get("block_id")
    very_tight = gap <= max(2.5, min(first_h, second_h) * 0.25)
    return parenthetical or connector or (same_block and very_tight)


def _complete_definition_terms_from_stage3(
    *,
    elements: list[CanonicalElement],
    pages: list[StructuredPage],
    extraction_by_page: dict[int, object],
    definition_pages: set[int],
) -> int:
    """Complete wrapped terms from immutable Stage-3 geometry.

    Earlier consolidation only worked when *both* wrapped lines survived as
    canonical elements.  Real parsers can omit one line while still keeping it
    in Stage 3.  This pass starts from a surviving term candidate, finds its
    matching Stage-3 line, and safely joins an adjacent wrapped line when the
    geometry and continuation cues are strong.
    """
    model = _definition_column_model(pages, definition_pages)
    completed = 0

    for page in pages:
        if page.page_number not in definition_pages:
            continue
        raw_page = extraction_by_page.get(page.page_number)
        if raw_page is None:
            continue
        width = max(page.width, 1.0)
        split_x = (model["split_ratio"] * width) if model is not None else width * 0.5
        raw_fragments = _stage3_left_line_fragments(raw_page, split_x)
        if len(raw_fragments) < 2:
            continue

        # Include already recovered terms as well as ordinary left-column term
        # candidates.  This is essential when only the acronym survived vendor
        # segmentation and was already promoted to ``definition_term``.
        candidates = [
            item for item in page.elements
            if item.type in {"definition_term", "paragraph", "list_item", "section_header", "page_footer"}
            and _looks_short_definition_term(item, width)
            and not _looks_definition_context(item.text)
        ]
        remove_ids: set[str] = set()

        for term in candidates:
            match_indexes = [
                idx for idx, fragment in enumerate(raw_fragments)
                if _raw_fragment_matches_element(fragment, term)
            ]
            if not match_indexes:
                continue
            match_index = min(
                match_indexes,
                key=lambda idx: abs(raw_fragments[idx]["bbox"][1] - term.bbox[1]),
            )

            pair: tuple[dict, dict] | None = None
            if match_index > 0:
                previous = raw_fragments[match_index - 1]
                current = raw_fragments[match_index]
                if _raw_term_fragment_continuation(previous, current, page_width=width):
                    pair = (previous, current)
            if pair is None and match_index + 1 < len(raw_fragments):
                current = raw_fragments[match_index]
                following = raw_fragments[match_index + 1]
                if _raw_term_fragment_continuation(current, following, page_width=width):
                    pair = (current, following)
            if pair is None:
                continue

            first, second = pair
            merged_text = " ".join(f"{first['text']} {second['text']}".split()).strip()
            if _normalized_match_text(merged_text) == _normalized_match_text(term.text):
                continue

            # Do not absorb a fragment already represented as another semantic
            # term.  This protects dense independent glossary rows.
            fragment_boxes = [first["bbox"], second["bbox"]]
            conflicting = [
                other for other in page.elements
                if other.element_id != term.element_id
                and other.type == "definition_term"
                and any(_overlap_ratio(other.bbox, box) >= 0.75 for box in fragment_boxes)
                and _normalized_match_text(other.text) not in {
                    _normalized_match_text(term.text),
                    _normalized_match_text(first["text"]),
                    _normalized_match_text(second["text"]),
                }
            ]
            if conflicting:
                continue

            term.text = merged_text
            merged_bbox = _union_bbox(fragment_boxes)
            if merged_bbox is not None:
                term.bbox = merged_bbox
            term.type = "definition_term"
            term.heading_level = None
            term.heading_level_source = None
            term.role_source = "definition_multiline_term_stage3_completion"
            term.source.stage3_block_ids = list(dict.fromkeys(
                term.source.stage3_block_ids + [first["block_id"], second["block_id"]]
            ))

            # If a vendor canonical fragment exactly represents either raw line,
            # remove it so the completed term is the only semantic region.
            for other in page.elements:
                if other.element_id == term.element_id:
                    continue
                if other.definition_entry_id is not None:
                    continue
                other_norm = _normalized_match_text(other.text)
                if other_norm in {_normalized_match_text(first["text"]), _normalized_match_text(second["text"])}:
                    if any(_overlap_ratio(other.bbox, box) >= 0.7 for box in fragment_boxes):
                        remove_ids.add(other.element_id)
            completed += 1

        if remove_ids:
            page.elements = [item for item in page.elements if item.element_id not in remove_ids]

    if completed:
        _reindex_canonical_elements(elements, pages)
    return completed


def _matching_stage3_span_bbox(raw_page, element: CanonicalElement) -> list[float] | None:
    """Find the actual Stage-3 span geometry supporting a recovered element."""
    target = _normalized_match_text(element.text)
    if not target:
        return None
    source_ids = set(element.source.stage3_block_ids)
    matched: list[list[float]] = []

    for block in raw_page.blocks:
        if getattr(block, "type", None) != "text":
            continue
        if source_ids and block.block_id not in source_ids:
            continue
        for line in block.lines:
            for span in line.spans:
                value = _normalized_match_text(span.text)
                if not value:
                    continue
                # Prefer exact fragment containment.  A token-overlap fallback
                # handles minor punctuation / ligature differences.
                contained = value in target or target in value
                if not contained:
                    stopwords = {
                        "a", "an", "the", "of", "to", "and", "or", "in", "for", "on",
                        "with", "is", "are", "be", "this", "that", "as", "by", "from",
                    }
                    span_tokens = {token for token in value.split() if token not in stopwords}
                    target_tokens = {token for token in target.split() if token not in stopwords}
                    if not span_tokens:
                        continue
                    overlap = len(span_tokens & target_tokens) / len(span_tokens)
                    if overlap < 0.75:
                        continue
                # Source provenance already narrows the search strongly; when
                # unavailable, require geometric proximity to avoid matching a
                # repeated word elsewhere on the page.
                if not source_ids:
                    expanded = [
                        element.bbox[0] - 6.0,
                        element.bbox[1] - 6.0,
                        element.bbox[2] + 6.0,
                        element.bbox[3] + 6.0,
                    ]
                    if _intersection(span.bbox, expanded) <= 0:
                        continue
                matched.append(list(span.bbox))

    return _union_bbox(matched)


def _snap_recovered_text_geometry_to_stage3(
    *,
    pages: list[StructuredPage],
    extraction_by_page: dict[int, object],
) -> int:
    """Remove synthetic blank extensions by snapping to real Stage-3 spans.

    Only recovered definition text/term elements are adjusted.  Immutable
    layout elements and table-backed semantic rows are left untouched.
    """
    adjusted = 0
    for page in pages:
        raw_page = extraction_by_page.get(page.page_number)
        if raw_page is None:
            continue
        for item in page.elements:
            if item.type not in {"definition_term", "definition_text"}:
                continue
            if not item.role_source.startswith("definition_"):
                continue
            # Table-derived glossary rows are also eligible when Stage 3 has
            # supporting text spans.  If a table has no text-layer evidence,
            # ``_matching_stage3_span_bbox`` simply returns None and the
            # semantic table geometry is preserved unchanged.
            supported = _matching_stage3_span_bbox(raw_page, item)
            if supported is None or _area(supported) <= 1.0:
                continue
            # Never enlarge a synthetic box dramatically.  The purpose of this
            # pass is to remove unsupported blank geometry or make a small
            # provenance-backed correction.
            current_area = max(_area(item.bbox), 1.0)
            supported_area = _area(supported)
            if supported_area > current_area * 1.6:
                continue
            if any(abs(a - b) > 0.75 for a, b in zip(item.bbox, supported)):
                item.bbox = [round(float(value), 3) for value in supported]
                adjusted += 1
    return adjusted

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
    span_items = [
        item for item in iter_page_spans(page_extraction)
        if _overlap_ratio(item.bbox, bbox) >= 0.35
    ]
    line_ids = list(dict.fromkeys(item.line_id for item in span_items))
    span_ids = [item.span_id for item in span_items]
    table_ids = [
        table.table_id
        for table in page_extraction.tables
        if _overlap_ratio(table.bbox, bbox) >= 0.35
    ]
    return CanonicalSourceTrace(
        layout_box_index=box_index,
        layout_box_class=boxclass,
        stage3_block_ids=block_ids,
        stage3_line_ids=line_ids,
        stage3_span_ids=span_ids,
        stage3_table_ids=table_ids,
    )


def _bind_recovered_definition_sources(
    *,
    raw_page,
    term: CanonicalElement,
    definition: CanonicalElement,
    role_source: str,
) -> None:
    """Attach precise Stage-3 provenance to a recovered definition pair.

    Recovered glossary rows are often split out of one coarse Stage-4 region.
    Copying the parent element's source trace makes every synthetic term/text
    child claim the same large set of Stage-3 spans.  That is useful as broad
    provenance, but it is *not* exact span provenance and breaks span-level
    correction later.

    Recompute the trace from each child bbox and then remove any span that is
    claimed by both sides.  A shared Stage-3 span means the extractor itself did
    not preserve a trustworthy geometric split; in that case we keep block/table
    provenance but deliberately avoid pretending that the span belongs exactly
    to either child.
    """
    term_box_index = term.source.layout_box_index
    term_box_class = term.source.layout_box_class
    definition_box_index = definition.source.layout_box_index
    definition_box_class = definition.source.layout_box_class
    term.source = _source_trace(raw_page, term.bbox, term_box_index, term_box_class)
    definition.source = _source_trace(raw_page, definition.bbox, definition_box_index, definition_box_class)

    shared = set(term.source.stage3_span_ids) & set(definition.source.stage3_span_ids)
    if not shared:
        return

    span_to_line = {item.span_id: item.line_id for item in iter_page_spans(raw_page)}
    term.source.stage3_span_ids = [span_id for span_id in term.source.stage3_span_ids if span_id not in shared]
    definition.source.stage3_span_ids = [span_id for span_id in definition.source.stage3_span_ids if span_id not in shared]
    term_lines = {span_to_line[span_id] for span_id in term.source.stage3_span_ids if span_id in span_to_line}
    definition_lines = {span_to_line[span_id] for span_id in definition.source.stage3_span_ids if span_id in span_to_line}
    term.source.stage3_line_ids = [line_id for line_id in term.source.stage3_line_ids if line_id in term_lines]
    definition.source.stage3_line_ids = [line_id for line_id in definition.source.stage3_line_ids if line_id in definition_lines]


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

    # Cover titles are sometimes returned as ordinary text boxes.  Include a
    # paragraph only when display typography is substantially larger than the
    # first-page body font; this keeps normal prose out of the document-role
    # candidate set while allowing a visually dominant cover title to be
    # recovered deterministically.
    first_page_fonts = sorted(
        float(element.dominant_font_size)
        for element in first_page_elements
        if element.dominant_font_size and element.dominant_font_size > 0
    )
    median_font = first_page_fonts[len(first_page_fonts) // 2] if first_page_fonts else 0.0

    header_like = [
        element
        for element in first_page_elements
        if (
            element.type in {"title", "section_header"}
            or (
                element.type == "paragraph"
                and element.dominant_font_size is not None
                and float(element.dominant_font_size) >= max(16.0, median_font * 1.45)
            )
        )
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
                if element.type in {"section_header", "paragraph"}
                and _is_centered(element, page_width)
                and _numbering_depth(element.text) is None
                and not _looks_question(element.text)
                and len(" ".join(element.text.split())) <= 240
                and element.bbox[1] <= page_height * (0.45 if element.type == "paragraph" else 0.24)
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
    if not text or text.isdigit():
        return False
    if element.type in {
        "title",
        "subtitle",
        "document_metadata",
        "section_header",
        "group_header",
        "definition_term",
        "page_header",
        "figure",
        "table",
    }:
        return False

    # Very short introducers such as ``means—`` or ``includes:`` are valid
    # definition content even though they are shorter than an ordinary prose
    # block.  This matters when the actual list starts on the next page.
    short_intro = bool(DEFINITION_INTRO.match(text)) or (
        len(text) >= 4 and text.rstrip().endswith(("—", "–", "-", ":"))
    )
    if len(text) < 12 and not short_intro:
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


def _definition_table_profile(element: CanonicalElement) -> dict | None:
    """Classify a vendor table as glossary-like using repeated row semantics.

    The decision is deliberately conservative: a two-column table alone is not
    enough.  We require repeated short term-like left cells, substantive right
    cells, and a strong majority of rows that follow that pattern.  Blank-left
    continuation rows are retained only after the table itself qualifies.
    """
    if element.type != "table" or element.table is None or element.table.col_count < 2:
        return None

    row_infos: list[dict] = []
    considered = 0
    valid_pairs = 0
    continuation_rows = 0
    left_lengths: list[int] = []
    right_lengths: list[int] = []

    for row_index, row in enumerate(element.table.cells):
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
            row_infos.append({"row_index": row_index, "kind": "header", "term": term, "definition": definition})
            continue

        considered += 1
        if term and definition and _looks_definition_term_text(term) and len(definition) >= 8:
            valid_pairs += 1
            left_lengths.append(len(term))
            right_lengths.append(len(definition))
            row_infos.append({"row_index": row_index, "kind": "pair", "term": term, "definition": definition})
        elif not term and len(definition) >= 8:
            continuation_rows += 1
            row_infos.append({"row_index": row_index, "kind": "continuation", "term": "", "definition": definition})
        else:
            row_infos.append({"row_index": row_index, "kind": "other", "term": term, "definition": definition})

    if considered == 0 or valid_pairs < 2:
        return None
    pair_ratio = valid_pairs / considered
    if pair_ratio < 0.55:
        return None

    # The explanatory side should generally be substantially richer than the
    # label side.  This filters ordinary key/value or numeric tables that happen
    # to have two columns.
    avg_left = sum(left_lengths) / max(len(left_lengths), 1)
    avg_right = sum(right_lengths) / max(len(right_lengths), 1)
    if avg_right < max(12.0, avg_left * 1.35):
        return None

    return {
        "rows": row_infos,
        "valid_pair_count": valid_pairs,
        "continuation_row_count": continuation_rows,
        "pair_ratio": pair_ratio,
    }


def _definition_table_rows(element: CanonicalElement) -> list[tuple[str, str]]:
    """Compatibility wrapper returning only complete glossary rows."""
    profile = _definition_table_profile(element)
    if profile is None:
        return []
    return [
        (row["term"], row["definition"])
        for row in profile["rows"]
        if row["kind"] == "pair"
    ]


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


def _infer_definition_model_from_stage3_page(raw_page, page_width: float, page_height: float) -> dict[str, float] | None:
    """Infer a two-column glossary split when no reliable canonical row exists yet."""
    raw_lines = _stage3_lines_in_region(raw_page, [0.0, 0.0, page_width, page_height])
    spans = [span for line in raw_lines for span in line["spans"] if span.text.strip()]
    if len(spans) < 4:
        return None
    ordered = sorted(spans, key=lambda span: (span.bbox[0], span.bbox[2]))
    candidates: list[tuple[float, float]] = []
    for left, right in zip(ordered, ordered[1:]):
        gap = right.bbox[0] - left.bbox[2]
        split = (left.bbox[2] + right.bbox[0]) / 2.0
        if gap >= page_width * 0.06 and page_width * 0.24 <= split <= page_width * 0.76:
            candidates.append((gap, split))
    if not candidates:
        return None
    _, split = max(candidates, key=lambda item: item[0])
    left_spans = [span for span in spans if (span.bbox[0] + span.bbox[2]) / 2.0 < split]
    right_spans = [span for span in spans if (span.bbox[0] + span.bbox[2]) / 2.0 >= split]
    if len(left_spans) < 2 or len(right_spans) < 2:
        return None
    term_left = _median([span.bbox[0] / page_width for span in left_spans]) or 0.0
    term_right = _median([span.bbox[2] / page_width for span in left_spans]) or (split / page_width)
    definition_left = _median([span.bbox[0] / page_width for span in right_spans]) or (split / page_width)
    return {
        "split_ratio": split / page_width,
        "definition_left_ratio": definition_left,
        "term_left_ratio": term_left,
        "term_right_ratio": term_right,
        "sample_count": 0.0,
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
    """Recover logical glossary rows from Stage-3 span geometry.

    This implementation works whether the left/right content appears in the same
    Stage-3 line, in separate parallel text blocks, or in a mixture of both.
    Vendor layout grouping is therefore not part of the row identity.
    """
    raw_lines = _stage3_lines_in_region(raw_page, element.bbox)
    split_x = _infer_definition_split_x(
        raw_lines=raw_lines, element=element, page_width=page_width, model=model
    )
    if split_x is None:
        return []

    fragments: list[dict] = []
    line_heights: list[float] = []
    for line in raw_lines:
        left_spans = []
        right_spans = []
        crossing_single = False
        for span in line["spans"]:
            center = (span.bbox[0] + span.bbox[2]) / 2.0
            if (
                len(line["spans"]) == 1
                and span.bbox[0] < split_x < span.bbox[2]
                and (span.bbox[2] - span.bbox[0]) > page_width * 0.25
            ):
                crossing_single = True
            if center < split_x:
                left_spans.append(span)
            else:
                right_spans.append(span)
        if crossing_single:
            # A single spanning run has no trustworthy coordinate split.  The
            # conservative lexical fallback handles this representation later.
            continue

        left_text = " ".join(span.text.strip() for span in left_spans if span.text.strip()).strip()
        right_text = " ".join(span.text.strip() for span in right_spans if span.text.strip()).strip()
        if not left_text and not right_text:
            continue
        y0 = float(line["bbox"][1])
        y1 = float(line["bbox"][3])
        line_heights.append(max(1.0, y1 - y0))
        fragments.append({
            "left_text": left_text,
            "right_text": right_text,
            "left_boxes": [list(span.bbox) for span in left_spans],
            "right_boxes": [list(span.bbox) for span in right_spans],
            "y0": y0,
            "y1": y1,
        })

    if not fragments:
        return []
    median_height = _median(line_heights) or 10.0
    join_gap = max(4.0, median_height * 0.75)

    # Build term anchors from the left stream.  Close left-only lines are joined
    # into a multi-line term (for example ``beneficial`` + ``owner``), whereas a
    # line that already carries right-column text is always treated as a new row.
    term_clusters: list[dict] = []
    for fragment in [item for item in fragments if item["left_text"]]:
        if term_clusters:
            previous = term_clusters[-1]
            gap = fragment["y0"] - previous["last_y1"]
            if (
                gap <= join_gap
                and not previous["had_right_text"]
                and not fragment["right_text"]
            ):
                previous["parts"].append(fragment["left_text"])
                previous["boxes"].extend(fragment["left_boxes"])
                previous["last_y1"] = fragment["y1"]
                continue
        term_clusters.append({
            "parts": [fragment["left_text"]],
            "boxes": list(fragment["left_boxes"]),
            "y0": fragment["y0"],
            "last_y1": fragment["y1"],
            "had_right_text": bool(fragment["right_text"]),
        })

    term_clusters = [
        cluster for cluster in term_clusters
        if _looks_definition_term_text(" ".join(cluster["parts"]))
    ]
    if not term_clusters:
        return []

    right_fragments = [item for item in fragments if item["right_text"]]
    recovered: list[dict] = []
    for index, cluster in enumerate(term_clusters):
        next_y = term_clusters[index + 1]["y0"] if index + 1 < len(term_clusters) else element.bbox[3] + 1.0
        start_y = cluster["y0"] - max(4.0, median_height * 0.5)
        definition_parts: list[str] = []
        definition_boxes: list[list[float]] = []
        for fragment in right_fragments:
            if fragment["y0"] < start_y or fragment["y0"] >= next_y - max(2.0, median_height * 0.25):
                continue
            definition_parts.append(fragment["right_text"])
            definition_boxes.extend(fragment["right_boxes"])

        term = " ".join(cluster["parts"]).strip()
        definition = " ".join(definition_parts).strip()
        term_bbox = _union_bbox(cluster["boxes"])
        definition_bbox = _union_bbox(definition_boxes)
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



_TEXTUAL_CANONICAL_TYPES = {
    "title", "subtitle", "document_metadata", "section_header", "group_header", "clause", "subclause",
    "definition_term", "definition_text", "paragraph", "list_item", "caption",
    "page_header", "page_footer", "footnote", "unknown",
}


def _cleanup_reconstructed_elements(
    elements: list[CanonicalElement],
    pages: list[StructuredPage],
    extraction_by_page: dict[int, object] | None = None,
) -> int:
    """Remove reconstruction artifacts without discarding meaningful visuals.

    Synthetic recovery can occasionally leave an empty text region or an exact
    duplicate after a vendor box has been split.  Empty textual boxes, degenerate
    geometry and near-identical overlapping duplicates are removed here.  Tables,
    figures and formulas are kept even when their text field is empty because
    their semantic content may be non-textual.
    """
    removed = 0
    if extraction_by_page:
        _snap_recovered_text_geometry_to_stage3(
            pages=pages,
            extraction_by_page=extraction_by_page,
        )
    for page in pages:
        cleaned: list[CanonicalElement] = []
        for item in page.elements:
            text = " ".join(item.text.split()).strip()
            if item.type in _TEXTUAL_CANONICAL_TYPES and not text:
                removed += 1
                continue
            if item.type in _TEXTUAL_CANONICAL_TYPES and _area(item.bbox) <= 1.0:
                removed += 1
                continue

            duplicate_index = None
            if text:
                for idx, existing in enumerate(cleaned):
                    existing_text = " ".join(existing.text.split()).strip()
                    same_source = (
                        existing.source.layout_box_index == item.source.layout_box_index
                        or bool(set(existing.source.stage3_block_ids) & set(item.source.stage3_block_ids))
                    )
                    text_related = (
                        existing_text == text
                        or (existing_text and text and (existing_text in text or text in existing_text))
                    )
                    if (
                        existing.type == item.type
                        and text_related
                        and _overlap_ratio(existing.bbox, item.bbox) >= (0.78 if same_source else 0.92)
                    ):
                        duplicate_index = idx
                        break
            if duplicate_index is None:
                cleaned.append(item)
                continue

            existing = cleaned[duplicate_index]
            # Prefer the element already participating in semantic structure;
            # otherwise prefer a recovered semantic role over raw layout.
            existing_strength = (
                int(existing.definition_entry_id is not None)
                + int(existing.role_source != "layout")
                + int(len(existing_text) >= len(text))
            )
            item_strength = (
                int(item.definition_entry_id is not None)
                + int(item.role_source != "layout")
                + int(len(text) > len(existing_text))
            )
            if item_strength > existing_strength:
                _merge_source_trace(item, existing)
                cleaned[duplicate_index] = item
            else:
                _merge_source_trace(existing, item)
            removed += 1

        page.elements = cleaned

    if removed:
        _reindex_canonical_elements(elements, pages)
    return removed


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

                _bind_recovered_definition_sources(
                    raw_page=raw_page,
                    term=term,
                    definition=definition,
                    role_source=row["source"],
                )

                new_elements.extend([term, definition])
                recovered_count += 1

        page.elements = new_elements

    if recovered_count:
        _reindex_canonical_elements(elements, pages)
    return recovered_count



def _vertical_overlap_ratio(a: list[float], b: list[float]) -> float:
    overlap = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    denom = max(1.0, min(a[3] - a[1], b[3] - b[1]))
    return overlap / denom


def _definition_split_x(page_width: float, model: dict[str, float] | None, bbox: list[float]) -> float:
    if model is not None:
        split = model["split_ratio"] * page_width
        if bbox[0] + page_width * 0.06 < split < bbox[2] - page_width * 0.06:
            return split
    return bbox[0] + (bbox[2] - bbox[0]) * 0.43


def _make_definition_pair_elements(
    *,
    term_source: CanonicalElement,
    definition_source: CanonicalElement,
    base_id: str,
    row_index: int,
    row: dict,
    role_source: str,
    raw_page=None,
) -> tuple[CanonicalElement, CanonicalElement]:
    term = term_source.model_copy(deep=True)
    definition = definition_source.model_copy(deep=True)
    term.element_id = f"{base_id}-r{row_index}-term"
    definition.element_id = f"{base_id}-r{row_index}-definition"

    term.type = "definition_term"
    term.text = row["term"]
    term.bbox = row["term_bbox"]
    term.definition_entry_id = None
    term.heading_level = None
    term.heading_level_source = None
    term.table = None
    term.role_source = role_source

    definition.type = "definition_text"
    definition.text = row["definition"]
    definition.bbox = row["definition_bbox"]
    definition.definition_entry_id = None
    definition.heading_level = None
    definition.heading_level_source = None
    definition.table = None
    definition.role_source = role_source
    if raw_page is not None:
        _bind_recovered_definition_sources(
            raw_page=raw_page,
            term=term,
            definition=definition,
            role_source=role_source,
        )
    return term, definition


def _recover_parallel_definition_columns(
    *,
    elements: list[CanonicalElement],
    pages: list[StructuredPage],
    extraction_by_page: dict[int, object],
    definition_pages: set[int],
) -> int:
    """Recover many logical rows hidden inside coarse parallel column boxes.

    Some layout engines emit one tall box for a sequence of glossary terms and
    one tall box for all corresponding definitions.  We use Stage-3 line/span
    geometry to recover the logical rows, rather than relying on the vendor box
    segmentation.  At least two valid rows are required before a coarse region
    is rewritten, which keeps the pass conservative.
    """
    global_model = _definition_column_model(pages, definition_pages)

    recovered_count = 0
    for page in pages:
        if page.page_number not in definition_pages:
            continue
        raw_page = extraction_by_page.get(page.page_number)
        if raw_page is None:
            continue
        width = max(page.width, 1.0)
        model = global_model or _infer_definition_model_from_stage3_page(raw_page, width, max(page.height, 1.0))
        if model is None:
            continue
        split_x = model["split_ratio"] * width
        min_height = max(42.0, page.height * 0.055)

        allowed_left = {"paragraph", "list_item", "section_header", "page_footer"}
        allowed_right = {"paragraph", "list_item", "section_header", "subclause", "clause"}
        left_candidates = [
            item for item in page.elements
            if item.definition_entry_id is None
            and item.type in allowed_left
            and item.bbox[2] <= split_x + width * 0.06
            and item.bbox[0] < split_x - width * 0.08
            and item.bbox[3] - item.bbox[1] >= min_height
            and not _looks_definition_context(item.text)
        ]
        right_candidates = [
            item for item in page.elements
            if item.definition_entry_id is None
            and item.type in allowed_right
            and item.bbox[0] >= split_x - width * 0.06
            and item.bbox[2] > split_x + width * 0.08
            and item.bbox[3] - item.bbox[1] >= min_height
        ]
        if not left_candidates or not right_candidates:
            continue

        used: set[str] = set()
        replacements: dict[str, list[CanonicalElement]] = {}
        remove_ids: set[str] = set()

        for left in sorted(left_candidates, key=lambda item: item.bbox[1]):
            if left.element_id in used:
                continue
            overlapping = [
                right for right in right_candidates
                if right.element_id not in used
                and _vertical_overlap_ratio(left.bbox, right.bbox) >= 0.35
            ]
            if not overlapping:
                continue
            right = max(overlapping, key=lambda item: _vertical_overlap_ratio(left.bbox, item.bbox))
            union = _union_bbox([left.bbox, right.bbox])
            if union is None:
                continue
            probe = left.model_copy(deep=True)
            probe.bbox = union
            rows = _recover_rows_from_stage3_columns(
                raw_page=raw_page,
                element=probe,
                page_width=width,
                model=model,
            )
            # Rewriting a coarse parallel region is deliberately stricter than
            # ordinary one-row recovery: repeated structure is required.
            if len(rows) < 2:
                continue

            created: list[CanonicalElement] = []
            base_id = f"{left.element_id}-{right.element_id}-parallel"
            for row_index, row in enumerate(rows, start=1):
                term, definition = _make_definition_pair_elements(
                    term_source=left,
                    definition_source=right,
                    base_id=base_id,
                    row_index=row_index,
                    row=row,
                    role_source="definition_parallel_stream_recovery",
                    raw_page=raw_page,
                )
                created.extend([term, definition])
                recovered_count += 1

            replacements[left.element_id] = created
            remove_ids.update({left.element_id, right.element_id})
            used.update({left.element_id, right.element_id})

        if not replacements:
            continue

        new_elements: list[CanonicalElement] = []
        for item in page.elements:
            if item.element_id in replacements:
                new_elements.extend(replacements[item.element_id])
            elif item.element_id in remove_ids:
                continue
            else:
                new_elements.append(item)
        page.elements = new_elements

    if recovered_count:
        _reindex_canonical_elements(elements, pages)
    return recovered_count


def _table_row_geometry(
    *,
    table_element: CanonicalElement,
    raw_page,
    page_width: float,
    model: dict[str, float] | None,
    semantic_rows: list[dict],
) -> dict[int, tuple[list[float] | None, list[float]]]:
    """Return best-effort term/definition bboxes for semantic table rows."""
    geometry: dict[int, tuple[list[float] | None, list[float]]] = {}
    recovered = _recover_rows_from_stage3_columns(
        raw_page=raw_page,
        element=table_element,
        page_width=page_width,
        model=model,
    ) if raw_page is not None else []

    unused = list(recovered)
    for row in semantic_rows:
        if row["kind"] != "pair":
            continue
        normalized_term = _normalize_heading_text(row["term"])
        match_index = next(
            (
                idx for idx, candidate in enumerate(unused)
                if _normalize_heading_text(candidate["term"]) == normalized_term
                or (
                    normalized_term
                    and _normalize_heading_text(candidate["term"]).startswith(normalized_term)
                )
            ),
            None,
        )
        if match_index is not None:
            candidate = unused.pop(match_index)
            geometry[row["row_index"]] = (candidate["term_bbox"], candidate["definition_bbox"])

    total_rows = max(table_element.table.row_count if table_element.table else len(semantic_rows), 1)
    row_height = max(1.0, (table_element.bbox[3] - table_element.bbox[1]) / total_rows)
    split_x = _definition_split_x(page_width, model, table_element.bbox)
    gap = max(10.0, page_width * 0.025)
    for row in semantic_rows:
        if row["kind"] == "header" or row["row_index"] in geometry:
            continue
        y0 = table_element.bbox[1] + row_height * row["row_index"]
        y1 = min(table_element.bbox[3], y0 + row_height)
        term_bbox = None
        if row["kind"] == "pair":
            term_bbox = [table_element.bbox[0], y0, max(table_element.bbox[0], split_x - gap), y1]
        definition_bbox = [min(table_element.bbox[2], split_x + gap), y0, table_element.bbox[2], y1]
        geometry[row["row_index"]] = (
            [round(v, 3) for v in term_bbox] if term_bbox else None,
            [round(v, 3) for v in definition_bbox],
        )
    return geometry


def _normalize_definition_tables(
    *,
    elements: list[CanonicalElement],
    pages: list[StructuredPage],
    extraction_by_page: dict[int, object],
    definition_pages: set[int],
) -> int:
    """Promote glossary-like vendor tables into canonical definition rows.

    The original vendor table remains available in the immutable Layout JSON and
    in each synthetic element's source trace.  It is intentionally removed from
    canonical page blocks so Stage 5 sees definitions instead of a table merely
    because the layout engine chose a table representation.
    """
    model = _definition_column_model(pages, definition_pages)
    converted = 0
    for page in pages:
        if page.page_number not in definition_pages:
            continue
        raw_page = extraction_by_page.get(page.page_number)
        width = max(page.width, 1.0)
        new_elements: list[CanonicalElement] = []

        for element in page.elements:
            profile = _definition_table_profile(element)
            if profile is None:
                new_elements.append(element)
                continue

            semantic_rows = [row for row in profile["rows"] if row["kind"] in {"pair", "continuation"}]
            geometry = _table_row_geometry(
                table_element=element,
                raw_page=raw_page,
                page_width=width,
                model=model,
                semantic_rows=semantic_rows,
            )
            row_serial = 0
            for row in semantic_rows:
                row_serial += 1
                term_bbox, definition_bbox = geometry[row["row_index"]]
                if row["kind"] == "pair" and term_bbox is not None:
                    row_data = {
                        "term": row["term"],
                        "definition": row["definition"],
                        "term_bbox": term_bbox,
                        "definition_bbox": definition_bbox,
                    }
                    term, definition = _make_definition_pair_elements(
                        term_source=element,
                        definition_source=element,
                        base_id=f"{element.element_id}-table",
                        row_index=row_serial,
                        row=row_data,
                        role_source="definition_table_semantic_normalization",
                        raw_page=raw_page,
                    )
                    new_elements.extend([term, definition])
                    converted += 1
                elif row["kind"] == "continuation":
                    continuation = element.model_copy(deep=True)
                    continuation.element_id = f"{element.element_id}-table-r{row_serial}-continuation"
                    continuation.type = "definition_text"
                    continuation.text = row["definition"]
                    continuation.bbox = definition_bbox
                    continuation.table = None
                    continuation.definition_entry_id = None
                    continuation.heading_level = None
                    continuation.heading_level_source = None
                    continuation.role_source = "definition_table_semantic_normalization"
                    if raw_page is not None:
                        continuation.source = _source_trace(
                            raw_page,
                            continuation.bbox,
                            element.source.layout_box_index,
                            element.source.layout_box_class,
                        )
                    new_elements.append(continuation)

        page.elements = new_elements

    if converted:
        _reindex_canonical_elements(elements, pages)
    return converted


def _looks_definition_item_text(text: str) -> bool:
    return DEFINITION_ITEM_PREFIX.match(" ".join(text.split()).strip()) is not None


def _parse_definition_items(text: str) -> list[DefinitionSubItem]:
    """Parse repeated enumerated items without depending on one marker style."""
    normalized = " ".join(text.split()).strip()
    matches = list(DEFINITION_ITEM_ANYWHERE.finditer(normalized))
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


def _parse_definition_items_from_elements(parts: list[CanonicalElement]) -> list[DefinitionSubItem]:
    """Prefer element boundaries so trailing explanation is not swallowed by the last item."""
    items: list[DefinitionSubItem] = []
    for part in parts:
        normalized = " ".join(part.text.split()).strip()
        match = DEFINITION_ITEM_PREFIX.match(normalized)
        if match:
            value = normalized[match.end():].strip(" ;")
            if value:
                items.append(DefinitionSubItem(marker=match.group(1), text=value))
    if len(items) >= 2:
        return items
    joined = " ".join(part.text.strip() for part in parts if part.text.strip())
    return _parse_definition_items(joined)


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
    if element.type in {"section_header", "group_header"}:
        # A genuine unnumbered section/group heading is generally left/central rather
        # than deep in the right-hand continuation column.
        return element.bbox[0] <= page_width * 0.42 and len(text) <= 180
    return False



def _is_open_block_boundary(
    element: CanonicalElement,
    page_width: float,
    state: OpenBlockState,
) -> bool:
    """Context-aware boundary test shared by cross-page reconciliation passes."""
    if state.kind == "definition" and state.allow_enumerated_items and _looks_definition_item_text(element.text):
        return False
    return _is_strong_cross_page_boundary(element, page_width)


def _open_block_geometry_score(
    *,
    state: OpenBlockState,
    candidate: CanonicalElement,
    next_page: StructuredPage,
    first_candidate: bool,
) -> tuple[int, list[str]]:
    score = 0
    evidence: list[str] = []
    width = max(next_page.width, 1.0)
    x0_delta = abs(candidate.bbox[0] - state.expected_column[0])
    if x0_delta <= width * 0.045:
        score += 3
        evidence.append(f"left edge aligns with the {state.kind} column")
    elif x0_delta <= width * 0.09:
        score += 1
        evidence.append(f"left edge approximately aligns with the {state.kind} column")

    overlap = _horizontal_overlap_ratio(candidate.bbox, state.expected_column)
    if overlap >= 0.65:
        score += 2
        evidence.append(f"horizontal range overlaps the {state.kind} column")
    elif overlap >= 0.4:
        score += 1
        evidence.append(f"horizontal range partially overlaps the {state.kind} column")

    if first_candidate and candidate.bbox[1] <= next_page.height * 0.28:
        score += 2
        evidence.append("candidate begins near the top of the next page")
    return score, evidence

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

    if _hierarchy_marker(last_part.text) is not None:
        score += 2
        evidence.append("definition ends with an enumerated item that may continue on the next page")

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
    state = OpenBlockState(
        kind="definition",
        source_element_id=previous_part.element_id,
        page_number=previous_part.page_number,
        expected_column=expected_column,
        context_id=previous_part.definition_entry_id,
        allow_enumerated_items=True,
    )
    score, evidence = _open_block_geometry_score(
        state=state,
        candidate=candidate,
        next_page=next_page,
        first_candidate=first_candidate,
    )

    if previous_part.dominant_font_size and candidate.dominant_font_size:
        if abs(previous_part.dominant_font_size - candidate.dominant_font_size) <= 1.5:
            score += 1
            evidence.append("font size is compatible across the page break")

    text = " ".join(candidate.text.split()).strip()
    if text and not _is_open_block_boundary(candidate, max(next_page.width, 1.0), state):
        score += 1
        evidence.append("candidate is not a strong structural boundary")
    if text and (text[:1].islower() or DEFINITION_INTRO.match(text) or _looks_definition_item_text(text)):
        score += 1
        evidence.append("text begins like prose, a definition introducer, or an enumerated continuation")
    if _text_looks_incomplete(previous_part.text):
        score += 1
        evidence.append("previous fragment is incomplete")

    marker_relation, marker_score, marker_evidence = _marker_sequence_relation(
        previous_part, candidate, max(next_page.width, 1.0)
    )
    if marker_relation is not None:
        score += marker_score
        evidence.extend(marker_evidence)
        evidence.append(f"enumerated continuation behaves like a {marker_relation}")

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

        state = OpenBlockState(
            kind="definition",
            source_element_id=last_part.element_id,
            page_number=page.page_number,
            expected_column=expected_column,
            context_id=last_id,
            allow_enumerated_items=True,
        )

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
            if _is_open_block_boundary(element, page_width, state):
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
            if index > 0 and _is_open_block_boundary(element, page_width, state):
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
    _recover_parallel_definition_columns(
        elements=elements,
        pages=pages,
        extraction_by_page=extraction_by_page,
        definition_pages=definition_pages,
    )
    _normalize_definition_tables(
        elements=elements,
        pages=pages,
        extraction_by_page=extraction_by_page,
        definition_pages=definition_pages,
    )
    _consolidate_multiline_definition_terms(
        elements=elements,
        pages=pages,
        definition_pages=definition_pages,
    )
    _complete_definition_terms_from_stage3(
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
            if not term.role_source.startswith("definition_"):
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
                if not candidate.role_source.startswith("definition_"):
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
        from_table = any(
            item.role_source == "definition_table_semantic_normalization"
            for item in ordered
        )
        source_table_element_id = None
        if from_table:
            source_table_element_id = f"p{term.page_number}-e{term.source.layout_box_index + 1}"
        entries.append(
            DefinitionEntry(
                definition_id=definition_id,
                term=term.text,
                section_id=term.section_id,
                term_element_id=term.element_id,
                source_table_element_id=source_table_element_id,
                source_kind="table_rows" if from_table else "layout_columns",
                definition_text=definition_text,
                items=_parse_definition_items_from_elements(definition_parts),
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

        if APPENDIX_LABEL.match(element.text) or MAJOR_OUTLINE_LABEL.match(element.text):
            element.heading_level = 1
            element.heading_level_source = "numbering"
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


def _subclause_marker_token(value: str) -> str:
    return value.strip().strip("()[]{} ").rstrip(".)").lower()


def _subclause_marker_family(
    ordered: list[tuple[ClauseRecord, CanonicalElement]],
    index: int,
    *,
    indent_threshold: float = 10.0,
) -> str:
    """Resolve ambiguous legal markers such as ``(i)`` conservatively.

    Single-letter roman numerals are also valid alphabetic markers. We use
    neighbouring marker sequences first, then indentation, so ``(h) (i) (j)``
    stays alphabetic while ``(a) (i) (ii)`` is interpreted as a nested roman
    sequence. The result is intentionally limited to the two marker families
    Stage 4 currently promotes to ``subclause``.
    """
    record, element = ordered[index]
    token = _subclause_marker_token(record.number)
    if not token:
        return "unknown"
    if len(token) > 1 and _roman_value(token) is not None:
        return "roman"
    if len(token) != 1 or not token.isalpha():
        return "unknown"
    if token not in "ivxlcdm":
        return "alpha"

    def neighbour(offset: int):
        j = index + offset
        if 0 <= j < len(ordered):
            rec, el = ordered[j]
            return _subclause_marker_token(rec.number), el
        return "", None

    prev_token, prev_element = neighbour(-1)
    next_token, next_element = neighbour(1)

    if (len(prev_token) > 1 and _roman_value(prev_token) is not None) or (
        len(next_token) > 1 and _roman_value(next_token) is not None
    ):
        return "roman"

    # An ordinary alphabetic run disambiguates single-letter roman symbols.
    if len(prev_token) == 1 and prev_token.isalpha() and ord(token) == ord(prev_token) + 1:
        return "alpha"
    if len(next_token) == 1 and next_token.isalpha() and ord(next_token) == ord(token) + 1:
        return "alpha"

    # A visibly deeper ``(i)`` after an alphabetic item is a strong nested-list
    # signal even when there is no ``(ii)`` to disambiguate it.
    if prev_element is not None:
        prev_family = "alpha" if len(prev_token) == 1 and prev_token.isalpha() and prev_token not in "ivxlcdm" else None
        if prev_family == "alpha" and element.bbox[0] - prev_element.bbox[0] >= indent_threshold:
            return "roman"

    return "alpha"


def _infer_nested_subclause_parents(
    records: list[ClauseRecord],
    elements: list[CanonicalElement],
    *,
    protected_element_ids: set[str] | None = None,
) -> None:
    """Repair the flat Stage-4 clause hierarchy for nested legal enumerations.

    Earlier versions attached every ``subclause`` in a section to the latest
    numbered clause. That makes valid structures such as ``(a) -> (i),(ii)``
    and ``(b) -> (i),(ii)`` look like duplicate sibling markers. This pass
    keeps alphabetic items under the numbered clause and nests roman items under
    the nearest preceding alphabetic item when sequence/geometry supports it.

    Explicit Stage-4.5 structural edits can protect selected elements from
    automatic reassignment.
    """
    protected = protected_element_ids or set()
    element_by_id = {element.element_id: element for element in elements}
    ordered_records = sorted(
        [record for record in records if record.element_id in element_by_id],
        key=lambda record: element_by_id[record.element_id].document_order,
    )

    current_clause_by_section: dict[str | None, ClauseRecord] = {}
    group_by_parent: dict[str, list[tuple[ClauseRecord, CanonicalElement]]] = {}

    # First establish which top-level numbered clause each automatic subclause
    # belongs to. Existing explicit nested parents are preserved for protected
    # elements; all other legacy flat parents are eligible for refinement.
    for record in ordered_records:
        element = element_by_id[record.element_id]
        if record.kind == "clause":
            current_clause_by_section[record.section_id] = record
            continue
        if record.kind != "subclause":
            continue
        top = current_clause_by_section.get(record.section_id)
        if element.element_id in protected:
            continue
        # A genuinely parent-less subclause remains an orphan. The repair is
        # only allowed to refine the legacy *flat* parent assignment; it must
        # not invent a parent where Stage 4 had none.
        if record.parent_clause_id is None:
            element.parent_clause_id = None
            continue
        if top is None:
            record.parent_clause_id = None
            element.parent_clause_id = None
            continue
        record.parent_clause_id = top.clause_id
        element.parent_clause_id = top.clause_id
        group_by_parent.setdefault(top.clause_id, []).append((record, element))

    # Then refine each top-level group. Roman enumerations are commonly nested
    # under the latest alphabetic item; sequence-aware disambiguation prevents
    # alphabetic ``(h),(i),(j)`` from being mistaken for roman numbering.
    for top_clause_id, group in group_by_parent.items():
        group.sort(key=lambda pair: pair[1].document_order)
        latest_alpha: ClauseRecord | None = None
        latest_alpha_element: CanonicalElement | None = None
        for index, (record, element) in enumerate(group):
            if element.element_id in protected:
                continue
            family = _subclause_marker_family(group, index)
            if family == "alpha":
                record.parent_clause_id = top_clause_id
                element.parent_clause_id = top_clause_id
                latest_alpha = record
                latest_alpha_element = element
                continue
            if family == "roman" and latest_alpha is not None:
                token = _subclause_marker_token(record.number)
                deeper_indent = latest_alpha_element is not None and element.bbox[0] - latest_alpha_element.bbox[0] >= 6.0
                unmistakable_roman = len(token) > 1 or token == "i"
                if deeper_indent or unmistakable_roman:
                    record.parent_clause_id = latest_alpha.clause_id
                    element.parent_clause_id = latest_alpha.clause_id


def _build_clause_records(
    elements: list[CanonicalElement],
    sections: list[SectionRecord],
) -> tuple[list[ClauseRecord], list[StructuralRelation]]:
    section_element_by_id = {section.section_id: section.element_id for section in sections}
    records: list[ClauseRecord] = []
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

    _infer_nested_subclause_parents(records, elements)

    relations: list[StructuralRelation] = []
    record_by_id = {record.clause_id: record for record in records}
    element_by_id = {element.element_id: element for element in elements}
    for clause in records:
        element = element_by_id.get(clause.element_id)
        if element is None:
            continue
        if clause.kind == "clause" and clause.section_id and clause.section_id in section_element_by_id:
            relations.append(StructuralRelation(
                relation_id=f"rel-{len(relations) + 1}",
                type="belongs_to",
                source_element_id=element.element_id,
                target_element_id=section_element_by_id[clause.section_id],
                evidence="clause inherits active section",
            ))
        if clause.parent_clause_id and clause.parent_clause_id in record_by_id:
            parent = record_by_id[clause.parent_clause_id]
            relations.append(StructuralRelation(
                relation_id=f"rel-{len(relations) + 1}",
                type="parent_of",
                source_element_id=parent.element_id,
                target_element_id=element.element_id,
                evidence="subclause hierarchy inferred from marker sequence and indentation",
            ))
    return records, relations



def _introduces_enumeration_text(text: str) -> bool:
    normalized = " ".join((text or "").split()).strip()
    if not normalized:
        return False
    if normalized.endswith((":", "–", "—", "―")):
        return True
    return re.search(
        r"\b(?:the\s+following|as\s+follows|include(?:s|d)?|including|types?\s+of|categories?\s+of|"
        r"identified\s+by|identified\s+as|set\s+out\s+below|listed\s+below|comprise(?:s|d)?|consist(?:s|ed)?\s+of)\b",
        normalized,
        re.IGNORECASE,
    ) is not None


def _build_group_and_list_relations(
    elements: list[CanonicalElement],
    sections: list[SectionRecord],
) -> list[StructuralRelation]:
    """Build explicit local-group/list dependencies after semantic resolution.

    In addition to local ``group_header`` scope, this pass keeps the nearest
    clause/subclause or unnumbered list-introducing paragraph active.  The
    latter is important for structures such as ``subclause -> explanatory
    paragraph ending ':' -> nested roman list`` and for lists that continue on
    the next page.  Classification and ownership are deliberately separate:
    an item can be correctly labelled ``list_item`` but still be semantically
    incomplete until an explicit owner is recorded.
    """
    ordered = sorted(elements, key=lambda item: item.document_order)
    relations: list[StructuralRelation] = []
    relation_pairs: set[tuple[str, str, str]] = set()
    active_clause: CanonicalElement | None = None
    active_subclause: CanonicalElement | None = None
    active_group: CanonicalElement | None = None
    active_paragraph_intro: CanonicalElement | None = None
    # Stack of list items that themselves introduce nested enumerations.
    # It is geometry-driven so nested ownership can survive page breaks while
    # same-level siblings correctly close the previous local list scope.
    active_list_parents: list[CanonicalElement] = []
    active_section: str | None = None

    def add_relation(kind: str, source: CanonicalElement, target: CanonicalElement, evidence: str) -> None:
        key = (kind, source.element_id, target.element_id)
        if key in relation_pairs:
            return
        relation_pairs.add(key)
        relations.append(StructuralRelation(
            relation_id=f"rel-group-{len(relations) + 1}",
            type=kind,
            source_element_id=source.element_id,
            target_element_id=target.element_id,
            evidence=evidence,
        ))

    meaningful_types_to_skip = {"page_header", "page_footer", "footnote", "caption", "document_metadata", "title", "subtitle"}
    previous_meaningful: dict[str, CanonicalElement | None] = {}
    previous: CanonicalElement | None = None
    for item in ordered:
        if item.type in meaningful_types_to_skip or not item.text.strip():
            continue
        previous_meaningful[item.element_id] = previous
        previous = item

    for element in ordered:
        if element.type in meaningful_types_to_skip:
            continue

        if element.type == "section_header":
            prior = previous_meaningful.get(element.element_id)
            if active_group is not None and prior is not None and prior.element_id == active_group.element_id:
                add_relation(
                    "introduces",
                    active_group,
                    element,
                    "local group label immediately scopes the following outline heading",
                )
            active_section = element.section_id
            active_clause = None
            active_subclause = None
            active_group = None
            active_paragraph_intro = None
            active_list_parents.clear()
            continue

        if element.section_id != active_section:
            active_section = element.section_id
            active_clause = None
            active_subclause = None
            active_group = None
            active_paragraph_intro = None
            active_list_parents.clear()

        if element.type == "group_header":
            if (
                active_clause is not None
                and active_group is not None
                and element.section_id == active_clause.section_id
                and element.bbox[0] < active_group.bbox[0] - 18.0
            ):
                active_clause = None
                active_subclause = None
                active_group = None

            if active_clause is None and active_group is not None and active_group.section_id == element.section_id:
                add_relation(
                    "introduces",
                    active_group,
                    element,
                    "local group label immediately refines the active local group scope",
                )
            elif active_clause is not None and active_clause.section_id == element.section_id:
                add_relation(
                    "introduces",
                    active_clause,
                    element,
                    "local group header follows the active clause and scopes its following members",
                )
            active_group = element
            active_subclause = None
            active_paragraph_intro = None
            active_list_parents.clear()
            continue

        if element.type == "clause":
            if active_group is not None and active_group.section_id == element.section_id:
                add_relation(
                    "introduces",
                    active_group,
                    element,
                    "numbered clause is scoped by the immediately preceding local group header",
                )
            active_clause = element
            active_subclause = None
            active_group = None
            active_paragraph_intro = None
            active_list_parents.clear()
            continue

        if element.type == "subclause":
            active_subclause = element
            active_paragraph_intro = None
            active_list_parents.clear()
            # ClauseRecord hierarchy already owns the subclause itself.  Keep
            # the subclause active so a following nested list can be linked.
            continue

        if element.type == "list_item":
            owner: CanonicalElement | None = None
            evidence = ""
            current_x = float(element.bbox[0])

            # Close local list-parent scopes when reading order returns to the
            # same or a shallower indentation. A deeper marker remains a child
            # of the nearest list item that explicitly introduced a sub-list.
            while active_list_parents and current_x <= float(active_list_parents[-1].bbox[0]) + 8.0:
                active_list_parents.pop()

            if (
                active_list_parents
                and active_list_parents[-1].section_id == element.section_id
                and current_x >= float(active_list_parents[-1].bbox[0]) + 14.0
            ):
                owner = active_list_parents[-1]
                evidence = "nested list item is owned by the nearest list item that introduces a deeper enumeration"
            elif active_group is not None and active_group.section_id == element.section_id:
                owner = active_group
                evidence = "enumerated/list item is a member of the active local group"
            elif (
                active_paragraph_intro is not None
                and active_paragraph_intro.section_id == element.section_id
                and _introduces_enumeration_text(active_paragraph_intro.text)
            ):
                owner = active_paragraph_intro
                evidence = "list item follows an unnumbered paragraph that explicitly introduces an enumeration"
            elif active_subclause is not None and active_subclause.section_id == element.section_id:
                deeper_indent = current_x >= float(active_subclause.bbox[0]) + 14.0
                if _introduces_enumeration_text(active_subclause.text) or deeper_indent:
                    owner = active_subclause
                    evidence = "nested list item is scoped by the active subclause using list-introduction/indentation evidence"
            elif active_clause is not None and active_clause.section_id == element.section_id:
                if _introduces_enumeration_text(active_clause.text):
                    owner = active_clause
                    evidence = "list item follows a clause that explicitly introduces an enumeration"

            if owner is not None:
                add_relation("introduces", owner, element, evidence)

            # A list item such as ``(a) Customer risk factors:`` establishes a
            # nested local scope for following indented Roman/alphabetic items.
            # The stack is retained across page decorations so a sub-list can
            # continue onto the next physical page.
            if _introduces_enumeration_text(element.text):
                active_list_parents.append(element)
            continue

        if element.type == "paragraph":
            active_group = None
            # A paragraph is a new immediate semantic scope. If it introduces a
            # list, it becomes that list's owner; otherwise any active nested
            # list scope has ended.
            active_list_parents.clear()
            if _introduces_enumeration_text(element.text):
                # Keep clause/subclause state while making the paragraph the
                # immediate owner of the list it introduces.
                active_paragraph_intro = element
            else:
                active_paragraph_intro = None
            continue

        if element.type == "figure":
            active_group = None
            active_list_parents.clear()
            # A paragraph that explicitly says "the following" / "as follows:"
            # can semantically introduce a list even when the layout engine
            # inserts figure-like text regions between the paragraph and the
            # canonical list members. Preserve that paragraph only on the same
            # physical page and only while it still clearly introduces an
            # enumeration. Any later paragraph/section/clause closes the scope.
            if (
                active_paragraph_intro is None
                or active_paragraph_intro.page_number != element.page_number
                or not _introduces_enumeration_text(active_paragraph_intro.text)
            ):
                active_paragraph_intro = None
            continue

        if element.type in {"table", "definition_term", "definition_text"}:
            active_group = None
            active_paragraph_intro = None
            active_list_parents.clear()

    return relations


def _build_clause_tail_relations(
    elements: list[CanonicalElement],
    relationships: list[StructuralRelation],
) -> list[StructuralRelation]:
    """Attach unnumbered prose that resumes a parent clause after an embedded list.

    Legal/policy prose often has ``clause opening -> (a)/(b) list -> clause
    tail``.  The tail is not a new paragraph semantically and is not part of the
    final list item.  Rather than destructively merging across intervening list
    elements, record a child-to-parent ``belongs_to`` relation.
    """
    ordered = [
        item for item in sorted(elements, key=lambda value: value.document_order)
        if item.type not in {"page_header", "page_footer", "footnote", "caption", "document_metadata", "title", "subtitle"}
        and item.text.strip()
    ]
    by_clause_id = {item.clause_id: item for item in elements if item.clause_id}
    incoming_intro: dict[str, CanonicalElement] = {}
    by_id = {item.element_id: item for item in elements}
    for relation in relationships:
        if relation.type != "introduces":
            continue
        source = by_id.get(relation.source_element_id)
        if source is not None:
            incoming_intro[relation.target_element_id] = source

    result: list[StructuralRelation] = []
    seen: set[tuple[str, str]] = set()
    for index, element in enumerate(ordered):
        if element.type != "paragraph" or index == 0:
            continue
        previous = ordered[index - 1]
        if previous.type not in {"subclause", "list_item"}:
            continue

        parent: CanonicalElement | None = None
        if previous.type == "subclause" and previous.parent_clause_id:
            parent = by_clause_id.get(previous.parent_clause_id)
        elif previous.type == "list_item":
            owner = incoming_intro.get(previous.element_id)
            if owner is not None:
                if owner.type == "clause":
                    parent = owner
                elif owner.type == "subclause" and owner.parent_clause_id:
                    parent = by_clause_id.get(owner.parent_clause_id)

        if parent is None or parent.section_id != element.section_id:
            continue
        normalized = " ".join(element.text.split()).strip()
        if not normalized:
            continue
        resumes_parent = bool(normalized[:1].islower())
        introduces_nested_list = _introduces_enumeration_text(normalized)
        parent_open = _introduces_enumeration_text(parent.text)
        if not ((parent_open and resumes_parent) or introduces_nested_list):
            continue

        key = (element.element_id, parent.element_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(StructuralRelation(
            relation_id=f"rel-tail-{len(result) + 1}",
            type="belongs_to",
            source_element_id=element.element_id,
            target_element_id=parent.element_id,
            evidence=(
                "unnumbered prose immediately follows an embedded list/subclause run and resumes the active parent clause"
                if resumes_parent
                else "unnumbered prose immediately after a subclause remains in the parent clause scope and introduces a nested list"
            ),
        ))
    return result


def _reconcile_cross_page_open_text_blocks(pages: list[StructuredPage]) -> list[StructuralRelation]:
    """Reconcile generic text/list hierarchy across adjacent pages.

    The engine is deliberately document-agnostic. It combines page-edge
    geometry, section continuity, marker sequencing and textual completeness.
    Repeated page headers/footers are ignored, while a genuine new section
    header before the first candidate is a hard boundary.

    This pass records relations rather than concatenating content. Definitions
    and tables still use their richer specialized reconciliation, but share the
    same ``continues`` relationship vocabulary.
    """
    relations: list[StructuralRelation] = []
    ordered_pages = sorted(pages, key=lambda item: item.page_number)
    eligible = {"paragraph", "clause", "subclause", "list_item"}
    decorations = {"page_header", "page_footer", "footnote", "caption", "document_metadata"}

    for current, nxt in zip(ordered_pages, ordered_pages[1:]):
        current_body = [
            item for item in current.elements
            if item.type in eligible and item.text.strip()
        ]
        if not current_body:
            continue

        source = max(current_body, key=lambda item: item.document_order)
        source_marker = _hierarchy_marker(source.text)
        lower_enough = source.bbox[3] >= current.height * 0.76
        marker_lower_enough = source_marker is not None and source.bbox[3] >= current.height * 0.62
        if not (lower_enough or marker_lower_enough):
            continue

        later_meaningful = [
            item for item in current.elements
            if item.document_order > source.document_order
            and item.type not in decorations
            and item.text.strip()
        ]
        if later_meaningful:
            continue

        expected = [source.bbox[0], 0.0, source.bbox[2], 1.0]
        state = OpenBlockState(
            kind=source.type,
            source_element_id=source.element_id,
            page_number=current.page_number,
            expected_column=expected,
            context_id=source.section_id,
            allow_enumerated_items=source.type in {"list_item", "clause", "subclause"},
        )

        # Find the first meaningful next-page element. Running headers/footers
        # are ignored. A genuine new section before any body candidate closes
        # the previous hierarchy and prevents a false continuation.
        candidate: CanonicalElement | None = None
        for item in sorted(nxt.elements, key=lambda value: value.reading_order):
            if not item.text.strip() or item.type in decorations:
                continue
            if item.type in {"title", "subtitle", "figure", "table"}:
                break
            if item.type == "section_header":
                break
            if item.type in eligible:
                if item.bbox[1] <= nxt.height * 0.34:
                    candidate = item
                break
            # Unknown semantic content before the candidate makes the relation
            # ambiguous; leave it for human review instead of forcing a merge.
            break

        if candidate is None:
            continue

        if source.section_id and candidate.section_id and source.section_id != candidate.section_id:
            continue

        semantic_boundary = continuation_boundary_reason(source, candidate)
        if semantic_boundary is not None:
            # Semantic structure outranks geometric alignment for fresh starts.
            # In particular, a new numbered clause at the top of the next page
            # must not be linked as continuation of the previous page's clause.
            continue

        score, evidence = _open_block_geometry_score(
            state=state,
            candidate=candidate,
            next_page=nxt,
            first_candidate=True,
        )

        if source.bbox[3] >= current.height * 0.78:
            score += 2
            evidence.append("source element ends near the bottom of the previous page")
        elif source.bbox[3] >= current.height * 0.65:
            score += 1
            evidence.append("source element is in the lower region of the previous page")

        if source.section_id and candidate.section_id and source.section_id == candidate.section_id:
            score += 2
            evidence.append("both elements remain in the same active section")

        marker_relation, marker_score, marker_evidence = _marker_sequence_relation(
            source, candidate, max(nxt.width, 1.0)
        )
        if marker_relation is not None:
            score += marker_score
            evidence.extend(marker_evidence)
            evidence.append(f"marker geometry indicates a {marker_relation} hierarchy continuation")

        if _text_looks_incomplete(source.text):
            score += 2
            evidence.append("source text appears incomplete at the page break")

        candidate_text = " ".join(candidate.text.split()).strip()
        if candidate_text[:1].islower():
            score += 1
            evidence.append("next-page text begins like prose continuation")

        if source.dominant_font_size and candidate.dominant_font_size:
            if abs(source.dominant_font_size - candidate.dominant_font_size) <= 1.5:
                score += 1
                evidence.append("font size is compatible across pages")

        # Marker continuity is allowed to carry a complete sibling item across
        # the boundary; prose-only relations remain deliberately stricter.
        threshold = 7 if marker_relation is not None else 8
        if score < threshold:
            continue

        relations.append(
            StructuralRelation(
                relation_id=f"rel-open-{len(relations) + 1}",
                type="continues",
                source_element_id=source.element_id,
                target_element_id=candidate.element_id,
                evidence=(
                    f"open {source.type} continuation score={score}: "
                    + "; ".join(evidence)
                ),
            )
        )
    return relations


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
            and item.type in {"section_header", "group_header", "subtitle", "title", "paragraph"}
            and not APPENDIX_LABEL.match(item.text)
            and _extract_clause_number(item.text) is None
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


def _tables_form_cross_page_continuation(
    current_page: StructuredPage,
    next_page: StructuredPage,
    current: CanonicalElement,
    candidate: CanonicalElement,
) -> bool:
    """Return True only when two table fragments have strong continuation evidence.

    This shared predicate is used by both logical-table reconciliation and TOC
    context inheritance so the two passes cannot silently drift apart.
    """
    if current.table is None or candidate.table is None:
        return False
    if current.bbox[3] < current_page.height * 0.72:
        return False
    if candidate.bbox[1] > next_page.height * 0.30:
        return False
    if _has_substantive_content_before_table(next_page, candidate):
        return False
    if not _table_columns_compatible(current, candidate, max(current_page.width, next_page.width, 1.0)):
        return False
    if not _table_context_compatible(current, candidate):
        return False
    return True


def _inherit_toc_context_and_repair(
    pages: list[StructuredPage],
    explicit_toc_pages: set[int],
) -> set[int]:
    """Safely inherit TOC context across adjacent continuation pages.

    Explicit TOC pages are trusted anchors. A following page inherits that
    context only when its first table is a strong geometric continuation of the
    previous page's last table *and* both fragments independently look like a
    3-column number/title/page TOC. The inherited context can then propagate
    across additional adjacent continuation pages.

    Only the continuing table fragment is eligible for repair. Other tables on
    the same inherited page remain untouched.
    """
    page_by_number = {page.page_number: page for page in pages}
    active_toc_pages = set(explicit_toc_pages)

    for page_number in sorted(page_by_number):
        if page_number in explicit_toc_pages:
            continue

        previous_page = page_by_number.get(page_number - 1)
        current_page = page_by_number.get(page_number)
        if previous_page is None or current_page is None:
            continue
        if previous_page.page_number not in active_toc_pages:
            continue

        previous_tables = [
            item for item in previous_page.elements
            if item.type == "table" and item.table is not None
        ]
        current_tables = [
            item for item in current_page.elements
            if item.type == "table" and item.table is not None
        ]
        if not previous_tables or not current_tables:
            continue

        source = max(previous_tables, key=lambda item: (item.bbox[3], item.document_order))
        candidate = min(current_tables, key=lambda item: (item.bbox[1], item.document_order))

        if not _tables_form_cross_page_continuation(previous_page, current_page, source, candidate):
            continue
        if not _looks_like_toc_table(source.table.cells):
            continue
        if not _looks_like_toc_table(candidate.table.cells):
            continue

        active_toc_pages.add(page_number)
        _repair_canonical_toc_table(candidate)

    return active_toc_pages


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

            # Strong continuation evidence is shared with TOC-context
            # inheritance so both passes use exactly the same geometry and
            # semantic-boundary rules.
            if not _tables_form_cross_page_continuation(current_page, next_page, current, candidate):
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
                elif item.type in {"section_header", "group_header", "clause", "subclause"}:
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
    explicit_toc_pages: set[int] = set()
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
        page_has_toc_context = _page_has_explicit_toc_context(layout_page)
        if page_has_toc_context:
            explicit_toc_pages.add(page_number)
        for reading_order, box in enumerate(layout_page.get("boxes") or []):
            boxclass = str(box.get("boxclass") or "unknown")
            canonical_type = BOX_TYPE_MAP.get(boxclass, "unknown")
            bbox = _bbox_from_box(box)
            canonical_table = (
                _canonical_table(box, allow_toc_row_repair=page_has_toc_context)
                if canonical_type == "table"
                else None
            )
            element = CanonicalElement(
                element_id=f"p{page_number}-e{reading_order + 1}",
                type=canonical_type,
                page_number=page_number,
                reading_order=reading_order,
                document_order=document_order,
                bbox=bbox,
                text=_table_cells_text(canonical_table.cells) if canonical_table is not None else _box_text(box),
                dominant_font_size=_dominant_font_size(raw_page, bbox),
                layout_role=boxclass,
                role_source="layout",
                table=canonical_table,
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
    resolve_appendix_labels(elements)
    _refine_figure_roles(elements, pages)
    _assign_heading_levels(
        elements,
        layout_result,
        title_root_present=title_element is not None,
    )
    resolve_structural_semantics(elements, pages)
    resolve_heading_scopes(elements, pages)
    reconcile_same_page_semantic_continuity(elements, pages)
    resolve_appendix_title_scopes(elements)
    definition_relations = _refine_definition_lists(elements, pages, extraction_by_page)
    _refine_footnotes(pages)
    _cleanup_reconstructed_elements(elements, pages, extraction_by_page)
    for element in elements:
        backfill_classification(element)

    sections = _build_sections(elements)

    # Stage 4.5.8.5: carry explicit TOC context only across table fragments
    # that satisfy the same continuation evidence used by logical-table
    # reconciliation. This runs after section assignment so a conflicting
    # section boundary can also block inheritance.
    _inherit_toc_context_and_repair(pages, explicit_toc_pages)

    definitions = _build_definition_entries(elements, pages)
    definitions.extend(_build_table_definition_entries(elements, definitions, pages))
    clauses, clause_relations = _build_clause_records(elements, sections)
    group_list_relations = _build_group_and_list_relations(elements, sections)
    clause_tail_relations = _build_clause_tail_relations(elements, clause_relations + group_list_relations)
    open_block_relations = _reconcile_cross_page_open_text_blocks(pages)
    appendices, appendix_relations = _build_appendices(elements, sections, pages)
    logical_tables, table_relations = _build_logical_tables(pages)
    figures, figure_relations = _build_figures_and_relations(pages)
    relationships = (
        definition_relations
        + clause_relations
        + group_list_relations
        + clause_tail_relations
        + open_block_relations
        + appendix_relations
        + table_relations
        + figure_relations
    )

    calibrate_hierarchy_confidence(
        elements=elements,
        sections=sections,
        relationships=relationships,
    )

    semantic_validation = validate_semantic_structure(
        elements=elements,
        sections=sections,
        relationships=relationships,
    )
    warnings.extend(semantic_validation.warnings)

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
