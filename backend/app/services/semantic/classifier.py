from __future__ import annotations

from app.schemas import CanonicalElement, SemanticClassification, SemanticTypeAlternative


def _normalized_alternatives(
    selected_type: str,
    confidence: float,
    alternatives: list[tuple[str, float]] | None,
) -> list[SemanticTypeAlternative]:
    """Normalize alternative support into the probability mass left by confidence.

    ``confidence`` remains the selected type's deterministic support score.  If
    alternatives are supplied, their relative raw weights are preserved but
    scaled so selected + alternatives sums to 1.0.  This prevents UI values such
    as 70% selected + 44% alternative, which looked probabilistic but exceeded
    100%.
    """
    aggregated: dict[str, float] = {}
    for alt_type, raw_score in alternatives or []:
        if alt_type == selected_type:
            continue
        aggregated[alt_type] = aggregated.get(alt_type, 0.0) + max(0.0, float(raw_score))

    if not aggregated:
        return []

    remaining = max(0.0, 1.0 - confidence)
    raw_total = sum(aggregated.values())
    if raw_total <= 0.0:
        normalized = {key: 0.0 for key in aggregated}
    else:
        normalized = {
            key: remaining * value / raw_total
            for key, value in aggregated.items()
        }

    return [
        SemanticTypeAlternative(type=alt_type, score=max(0.0, min(1.0, score)))
        for alt_type, score in normalized.items()
    ]


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
    alt_models = _normalized_alternatives(selected_type, confidence, alternatives)
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
        classification = element.classification
        if classification.alternatives:
            total = classification.confidence + sum(item.score for item in classification.alternatives)
            if abs(total - 1.0) > 1e-9:
                apply_classification(
                    element,
                    classification.selected_type,
                    confidence=classification.confidence,
                    source=classification.source,
                    evidence=classification.evidence,
                    alternatives=[(item.type, item.score) for item in classification.alternatives],
                    mutate_type=False,
                )
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
