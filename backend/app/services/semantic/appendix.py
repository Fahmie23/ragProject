from __future__ import annotations

import re

from app.schemas import CanonicalElement
from app.services.semantic.classifier import apply_classification
from app.services.semantic.features import extract_clause_number


APPENDIX_LABEL_RE = re.compile(r"^\s*APPENDIX\s+([A-Z0-9IVXLC]+)\s*$", re.IGNORECASE)


def resolve_appendix_labels(elements: list[CanonicalElement]) -> None:
    """Promote explicit appendix labels to structural boundaries.

    Layout engines frequently label a top-right ``APPENDIX A`` / ``APPENDIX E``
    marker as a running page header.  An exact appendix label is stronger
    semantic evidence than that vendor layout role, so it must participate in
    the outline and appendix builder regardless of its original box class.

    The original layout role is retained on ``layout_role`` / ``source`` for
    provenance.  Only exact standalone labels are promoted; TOC rows and prose
    references such as "Appendix A of these Guidelines" are untouched.
    """
    for element in elements:
        text = " ".join((element.text or "").split()).strip()
        if not APPENDIX_LABEL_RE.fullmatch(text):
            continue
        if element.type == "section_header" and element.role_source == "semantic_appendix_boundary":
            continue

        element.heading_level = None
        element.heading_level_source = None
        element.section_id = None
        element.role_source = "semantic_appendix_boundary"
        apply_classification(
            element,
            "section_header",
            confidence=0.99,
            source="appendix_boundary_resolver",
            evidence=[
                "standalone text matches the canonical APPENDIX label pattern",
                f"vendor layout role '{element.layout_role or element.source.layout_box_class or 'unknown'}' is retained only as evidence",
                "appendix boundary semantics override running-header appearance",
            ],
            alternatives=[("page_header", 0.01)],
        )


def resolve_appendix_title_scopes(elements: list[CanonicalElement]) -> None:
    """Demote the descriptive appendix title from outline section to local scope.

    The first substantive unnumbered heading immediately following a standalone
    appendix label is already represented explicitly by ``AppendixRecord.title``.
    Keeping the same element as an empty ``SectionRecord`` duplicates structure
    and can distort the section stack.  Treat it as ``group_header`` instead.

    This is deliberately conservative: only same-page, immediately-following,
    unnumbered ``section_header`` elements are considered.  Numbered internal
    headings such as ``1.0 Introduction`` remain genuine outline sections.
    """
    ordered = sorted(elements, key=lambda item: item.document_order)
    ignored = {"page_header", "page_footer", "footnote", "caption", "document_metadata"}

    for index, label in enumerate(ordered):
        text = " ".join((label.text or "").split()).strip()
        if not APPENDIX_LABEL_RE.fullmatch(text):
            continue

        candidate: CanonicalElement | None = None
        for item in ordered[index + 1:]:
            if item.page_number != label.page_number:
                break
            if item.type in ignored or not (item.text or "").strip():
                continue
            candidate = item
            break

        if candidate is None or candidate.type != "section_header":
            continue
        candidate_text = " ".join((candidate.text or "").split()).strip()
        if APPENDIX_LABEL_RE.fullmatch(candidate_text):
            continue
        if extract_clause_number(candidate_text) is not None:
            continue

        candidate.heading_level = None
        candidate.heading_level_source = None
        candidate.section_id = None
        candidate.role_source = "semantic_appendix_title_scope"
        apply_classification(
            candidate,
            "group_header",
            confidence=0.94,
            source="appendix_title_scope_resolver",
            evidence=[
                "unnumbered heading immediately follows a standalone appendix boundary on the same page",
                "the same element is represented as the appendix descriptive title rather than a duplicate outline section",
                "numbered internal appendix headings remain eligible as SectionRecords",
                f"vendor layout role '{candidate.layout_role or candidate.source.layout_box_class or 'unknown'}' is retained as evidence",
            ],
            alternatives=[("section_header", 0.06)],
        )
