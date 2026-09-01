from __future__ import annotations

import re

from app.schemas import CanonicalElement


_EXPLICIT_ITEM_RE = re.compile(
    r"^\s*(?:[•●▪‣◦]|\((?:[A-Za-z]|\d{1,3}|[ivxlcdmIVXLCDM]{1,8})\)|(?:\d{1,3}|[A-Za-z])[.)])\s*"
)


def _starts_explicit_item(text: str) -> bool:
    return _EXPLICIT_ITEM_RE.match(text or "") is not None


def continuation_boundary_reason(
    source: CanonicalElement,
    candidate: CanonicalElement,
) -> str | None:
    """Return a hard semantic boundary reason for generic open-text continuation.

    ``continues`` means the *same semantic unit* carries across the page break.
    A fresh heading, numbered clause or explicit list/subclause marker starts a
    new unit even when geometry is perfectly aligned.  Cross-page sibling or
    parent/child hierarchy belongs in structural relationships, not in a
    ``continues`` edge.
    """
    if candidate.type in {"title", "subtitle", "section_header", "group_header", "definition_term"}:
        return f"target starts a fresh {candidate.type} semantic unit"

    if candidate.type == "clause" and candidate.clause_number:
        if source.element_id != candidate.element_id:
            return f"target starts fresh numbered clause {candidate.clause_number}"

    if _starts_explicit_item(candidate.text):
        return "target starts a fresh explicit enumerated/list item"

    return None
