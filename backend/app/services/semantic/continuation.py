from __future__ import annotations

from app.schemas import CanonicalElement


def continuation_boundary_reason(
    source: CanonicalElement,
    candidate: CanonicalElement,
) -> str | None:
    """Return a hard semantic boundary reason for generic open-text continuation.

    Geometry can strongly resemble continuation even when the next page starts a
    new numbered clause.  Stage 4 semantic classification is therefore allowed
    to veto the geometry-only relation.  The function is intentionally small and
    conservative: it blocks only explicit fresh semantic starts.
    """
    if candidate.type in {"title", "subtitle", "section_header", "group_header", "definition_term"}:
        return f"target starts a fresh {candidate.type} semantic unit"

    if candidate.type == "clause" and candidate.clause_number:
        if source.element_id != candidate.element_id:
            return f"target starts fresh numbered clause {candidate.clause_number}"

    return None
