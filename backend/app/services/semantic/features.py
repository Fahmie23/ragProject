from __future__ import annotations

from dataclasses import dataclass
import re
from statistics import median

from app.schemas import CanonicalElement, StructuredPage


_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’/-]*")
_CLAUSE_PREFIX_RE = re.compile(r"^\s*(?:(\d+(?:\s*[A-Z])?\.\d+(?:\.\d+){0,4}(?:[A-Z](?=\s))?)(?=\s|[A-Za-z])|(\d+)[.)](?=\s|[A-Za-z]))\s*", re.IGNORECASE)
_SUBCLAUSE_PREFIX_RE = re.compile(r"^\s*\(([a-z]|[ivxlcdm]+)\)\s*", re.IGNORECASE)
_MODAL_OR_FINITE_RE = re.compile(
    r"\b(?:shall|must|may|should|will|would|can|could|is|are|was|were|has|have|had|means?|includes?|"
    r"requires?|applies?|provides?|consists?|comprises?|refers?)\b",
    re.IGNORECASE,
)
_LIST_INTRO_RE = re.compile(
    r"\b(?:the\s+following|as\s+follows|include(?:s|d)?|including|comprise(?:s|d)?|consist(?:s|ed)?\s+of|"
    r"types?\s+of|categories?\s+of|items?\s+below|set\s+out\s+below)\b",
    re.IGNORECASE,
)
_TERMINAL_RE = re.compile(r"[.!?]\s*$")


@dataclass(frozen=True)
class ElementFeatures:
    element_id: str
    document_order: int
    page_number: int
    text: str
    normalized_text: str
    word_count: int
    x0: float
    y0: float
    x1: float
    y1: float
    width: float
    height: float
    page_width: float
    page_height: float
    x_ratio: float
    dominant_font_size: float | None
    page_median_font_size: float | None
    layout_role: str
    clause_number: str | None
    marker: str | None
    marker_token: str | None
    ends_colon: bool
    ends_semicolon: bool
    ends_comma: bool
    ends_period: bool
    ends_question: bool
    has_modal_or_finite: bool
    looks_sentence: bool
    looks_short_label: bool
    looks_list_intro: bool

    @property
    def is_enumerated(self) -> bool:
        return self.marker is not None

    @property
    def is_short_phrase(self) -> bool:
        return self.word_count <= 12 and not self.looks_sentence


def _normalized(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _normalize_ambiguous_article_a(text: str) -> str:
    """Do not mistake a glued prose article ``A`` for a clause suffix.

    Layout extraction can yield ``11.8A reporting...`` for source text
    ``11.8 A reporting...``. A genuine suffix such as ``11.6A A reporting``
    is intentionally left unchanged.
    """
    return re.sub(
        r"^(\s*\d+(?:\.\d+){1,5})A(?=\s+[a-z])",
        r"\1 A",
        text or "",
        count=1,
    )


def extract_clause_number(text: str) -> str | None:
    text = _normalize_ambiguous_article_a(text or "")
    match = _CLAUSE_PREFIX_RE.match(text)
    if not match:
        return None
    value = match.group(1) or match.group(2)
    return re.sub(r"\s+", "", value) if value else None


def extract_marker(text: str) -> tuple[str | None, str | None]:
    match = _SUBCLAUSE_PREFIX_RE.match(text or "")
    if not match:
        return None, None
    token = match.group(1)
    return f"({token})", token.lower()


def strip_marker(text: str) -> str:
    return _SUBCLAUSE_PREFIX_RE.sub("", text or "", count=1).strip()


def strip_clause_prefix(text: str) -> str:
    text = _normalize_ambiguous_article_a(text or "")
    return _CLAUSE_PREFIX_RE.sub("", text, count=1).strip()


def build_feature_map(
    elements: list[CanonicalElement],
    pages: list[StructuredPage],
) -> dict[str, ElementFeatures]:
    page_dims = {page.page_number: (max(float(page.width), 1.0), max(float(page.height), 1.0)) for page in pages}
    page_font_values: dict[int, list[float]] = {}
    for element in elements:
        if element.dominant_font_size and element.dominant_font_size > 0:
            page_font_values.setdefault(element.page_number, []).append(float(element.dominant_font_size))
    page_medians = {
        page: median(values) if values else None
        for page, values in page_font_values.items()
    }

    result: dict[str, ElementFeatures] = {}
    for element in elements:
        text = _normalized(element.text)
        width, height = page_dims.get(element.page_number, (1.0, 1.0))
        marker, token = extract_marker(text)
        words = _WORD_RE.findall(strip_marker(strip_clause_prefix(text)))
        has_finite = bool(_MODAL_OR_FINITE_RE.search(strip_marker(text)))
        ends_period = text.endswith(".")
        ends_question = text.endswith("?")
        looks_sentence = bool(
            ends_question
            or (ends_period and len(words) >= 4)
            or (has_finite and len(words) >= 5)
        )
        looks_short_label = bool(
            1 <= len(words) <= 10
            and not text.endswith((".", ";", ",", "?"))
            and not has_finite
            and extract_clause_number(text) is None
            and marker is None
        )
        result[element.element_id] = ElementFeatures(
            element_id=element.element_id,
            document_order=element.document_order,
            page_number=element.page_number,
            text=element.text,
            normalized_text=text,
            word_count=len(words),
            x0=float(element.bbox[0]),
            y0=float(element.bbox[1]),
            x1=float(element.bbox[2]),
            y1=float(element.bbox[3]),
            width=max(0.0, float(element.bbox[2]) - float(element.bbox[0])),
            height=max(0.0, float(element.bbox[3]) - float(element.bbox[1])),
            page_width=width,
            page_height=height,
            x_ratio=float(element.bbox[0]) / width,
            dominant_font_size=element.dominant_font_size,
            page_median_font_size=page_medians.get(element.page_number),
            layout_role=element.layout_role or element.source.layout_box_class or "unknown",
            clause_number=extract_clause_number(text),
            marker=marker,
            marker_token=token,
            ends_colon=text.endswith(":"),
            ends_semicolon=text.endswith(";"),
            ends_comma=text.endswith(","),
            ends_period=ends_period,
            ends_question=ends_question,
            has_modal_or_finite=has_finite,
            looks_sentence=looks_sentence,
            looks_short_label=looks_short_label,
            looks_list_intro=bool(text.endswith((":", "–", "—", "―")) or _LIST_INTRO_RE.search(text)),
        )
    return result
