from __future__ import annotations

from app.schemas import CanonicalElement, SemanticClassification, SemanticTypeAlternative


def apply_classification(
    element: CanonicalElement,
    selected_type: str,
    *,
    confidence: float,
    source: str,
    evidence: list[str],
    alternatives: list[tuple[str, float]] | None = None,
    mutate_type: bool = True,
) -> None:
    confidence = max(0.0, min(1.0, float(confidence)))
    alt_models = [
        SemanticTypeAlternative(type=alt_type, score=max(0.0, min(1.0, float(score))))
        for alt_type, score in (alternatives or [])
        if alt_type != selected_type
    ]
    if mutate_type:
        element.type = selected_type  # Pydantic validates on serialization boundaries.
    element.classification = SemanticClassification(
        selected_type=selected_type,
        confidence=confidence,
        source=source,
        evidence=list(dict.fromkeys(evidence)),
        alternatives=alt_models,
    )


def backfill_classification(element: CanonicalElement) -> None:
    """Ensure every element has auditable classification metadata.

    Specialized legacy resolvers can still change an element after the new
    sequence resolver. If the selected type no longer matches, preserve the
    final type as authoritative and record the existing ``role_source`` as the
    classifier source rather than leaving stale metadata behind.
    """
    if element.classification is not None and element.classification.selected_type == element.type:
        return
    role = element.role_source or "layout"
    confidence = 0.92 if role not in {"layout", "unknown"} else 0.72
    evidence = [
        f"final semantic type produced by Stage 4 source '{role}'",
        f"layout role '{element.layout_role or element.source.layout_box_class or 'unknown'}' retained as evidence",
    ]
    apply_classification(
        element,
        element.type,
        confidence=confidence,
        source=role,
        evidence=evidence,
        mutate_type=False,
    )
