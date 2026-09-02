from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.schemas import ChunkingArtifact, ClauseRecord, ResolvedStructureArtifact, StructuredDocument
from app.services.storage import read_chunking_artifact, read_resolved_structure


CITATION_VERSION = "deterministic_citations_v1_2"


class CitationSourceError(RuntimeError):
    """Raised when the source artifacts needed to render citations are unavailable."""


class CitationValidationError(RuntimeError):
    """Raised when claim/evidence/chunk/source provenance is inconsistent."""


@dataclass(frozen=True)
class CitationArtifacts:
    resolved: ResolvedStructureArtifact
    chunks: ChunkingArtifact


def _ordered_unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output


def _ordered_unique_int(values: Iterable[int]) -> list[int]:
    return sorted({int(value) for value in values})


def _page_text(pages: list[int]) -> str:
    if not pages:
        return "PDF page unavailable"
    if len(pages) == 1:
        return f"PDF p. {pages[0]}"
    contiguous = pages == list(range(pages[0], pages[-1] + 1))
    if contiguous:
        return f"PDF pp. {pages[0]}–{pages[-1]}"
    return "PDF pp. " + ", ".join(str(page) for page in pages)


def _marker_text(value: str) -> str:
    clean = value.strip()
    if not clean:
        return ""
    if clean.startswith("(") and clean.endswith(")"):
        return clean
    return f"({clean.strip('()')})"


def _clause_path(record: ClauseRecord, by_id: dict[str, ClauseRecord]) -> str:
    if record.kind == "clause":
        return record.number.strip()

    suffix: list[str] = []
    current: ClauseRecord | None = record
    seen: set[str] = set()
    while current is not None and current.clause_id not in seen:
        seen.add(current.clause_id)
        if current.kind == "clause":
            base = current.number.strip()
            return base + "".join(reversed(suffix))
        suffix.append(_marker_text(current.number))
        current = by_id.get(current.parent_clause_id or "")

    # A malformed/orphaned subclause should not silently be presented as a full
    # numbered clause. Its source marker remains usable as a deterministic locator.
    return "".join(reversed(suffix)) or _marker_text(record.number)


def _definition_source_ids(definition: Any) -> list[str]:
    ids: list[str] = []
    if definition.term_element_id:
        ids.append(definition.term_element_id)
    if definition.source_table_element_id:
        ids.append(definition.source_table_element_id)
    ids.extend(definition.definition_element_ids)
    return _ordered_unique(ids)


def _load_artifacts(document_id: str) -> CitationArtifacts:
    resolved = read_resolved_structure(document_id)
    if resolved is None:
        raise CitationSourceError("Resolved canonical structure is unavailable for citation rendering.")
    chunks = read_chunking_artifact(document_id)
    if chunks is None:
        raise CitationSourceError("Stage 5 chunk artifact is unavailable for citation rendering.")
    if resolved.document_id != document_id or chunks.document_id != document_id:
        raise CitationValidationError("Citation source artifacts do not match the requested document.")
    if chunks.source_sha256 != resolved.source_sha256:
        raise CitationValidationError("Stage 5 chunks and the resolved structure have different source hashes.")
    if chunks.source_resolved_at != resolved.resolved_at:
        raise CitationValidationError("Stage 5 chunks are stale relative to the resolved canonical structure.")
    return CitationArtifacts(resolved=resolved, chunks=chunks)


def validate_evidence_provenance(
    document_id: str,
    evidence: list[dict[str, Any]],
    *,
    artifacts: CitationArtifacts | None = None,
) -> CitationArtifacts:
    """Validate Stage 9 evidence against frozen Stage 5 + resolved structure.

    This function does not alter or re-run retrieval. It verifies that every
    request-local evidence object can be traced back to the exact frozen chunk
    and canonical source elements from which a human-facing citation is derived.
    """

    artifacts = artifacts or _load_artifacts(document_id)
    chunk_by_id = {chunk.chunk_id: chunk for chunk in artifacts.chunks.chunks}
    element_by_id = {
        element.element_id: element
        for page in artifacts.resolved.structure.pages
        for element in page.elements
    }

    seen_evidence_ids: set[str] = set()
    for row in evidence:
        evidence_id = str(row.get("evidence_id") or "")
        if not evidence_id or evidence_id in seen_evidence_ids:
            raise CitationValidationError(f"Duplicate or empty evidence ID in citation input: {evidence_id!r}.")
        seen_evidence_ids.add(evidence_id)

        chunk_id = str(row.get("chunk_id") or "")
        chunk = chunk_by_id.get(chunk_id)
        if chunk is None:
            raise CitationValidationError(f"{evidence_id} references unknown Stage 5 chunk {chunk_id!r}.")
        if int(row.get("chunk_index", -1)) != chunk.chunk_index:
            raise CitationValidationError(f"{evidence_id} chunk_index does not match frozen Stage 5 provenance.")
        if [int(x) for x in row.get("pages", [])] != list(chunk.pages):
            raise CitationValidationError(f"{evidence_id} pages do not match frozen Stage 5 provenance.")
        if [str(x) for x in row.get("section_path", [])] != list(chunk.section_path):
            raise CitationValidationError(f"{evidence_id} section_path does not match frozen Stage 5 provenance.")
        if [str(x) for x in row.get("source_element_ids", [])] != list(chunk.source_element_ids):
            raise CitationValidationError(f"{evidence_id} source_element_ids do not match frozen Stage 5 provenance.")

        missing = [element_id for element_id in chunk.source_element_ids if element_id not in element_by_id]
        if missing:
            raise CitationValidationError(
                f"{evidence_id} contains Stage 5 source element IDs missing from the resolved structure: {missing}."
            )
        canonical_pages = _ordered_unique_int(element_by_id[element_id].page_number for element_id in chunk.source_element_ids)
        if canonical_pages != list(chunk.pages):
            raise CitationValidationError(
                f"{evidence_id} canonical source pages {canonical_pages} disagree with frozen chunk pages {chunk.pages}."
            )

    return artifacts


def _source_locators(
    structure: StructuredDocument,
    source_element_ids: list[str],
    pages: list[int],
) -> list[dict[str, Any]]:
    element_by_id = {
        element.element_id: element
        for page in structure.pages
        for element in page.elements
    }
    source_id_set = set(source_element_ids)
    clause_by_id = {clause.clause_id: clause for clause in structure.clauses}
    clause_by_element = {clause.element_id: clause for clause in structure.clauses}
    appendix_by_id = {appendix.appendix_id: appendix for appendix in structure.appendices}
    appendix_by_label_element = {
        appendix.label_element_id: appendix
        for appendix in structure.appendices
        if getattr(appendix, "label_element_id", None)
    }
    section_by_id = {section.section_id: section for section in structure.sections}

    locators: list[dict[str, Any]] = []

    def effective_appendix_ref(element_id: str) -> tuple[str, str, str] | None:
        """Resolve appendix membership from explicit canonical provenance only.

        Resolution order is deliberately strict and deterministic:
        1. a direct ``CanonicalElement.appendix_id`` (which must resolve to an
           ``AppendixRecord``);
        2. an ancestor ``SectionRecord(kind="appendix")`` whose label element
           resolves to an ``AppendixRecord``;
        3. that explicit appendix SectionRecord itself when the frozen canonical
           artifact does not contain a duplicate ``AppendixRecord``.

        Step 3 is not inference: the canonical section is already explicitly
        typed as an appendix. We validate that its label element exists and its
        page agrees with the SectionRecord before using the section title as the
        human-facing appendix label. Page-range guessing remains forbidden.
        """

        element = element_by_id[element_id]
        if element.appendix_id:
            appendix = appendix_by_id.get(element.appendix_id)
            if appendix is None:
                raise CitationValidationError(
                    f"Canonical source references unknown appendix {element.appendix_id!r}."
                )
            return ("appendix_record", appendix.appendix_id, appendix.label)

        section_id = element.section_id or ""
        seen_sections: set[str] = set()
        while section_id and section_id not in seen_sections:
            seen_sections.add(section_id)
            section = section_by_id.get(section_id)
            if section is None:
                raise CitationValidationError(
                    f"Canonical source references unknown section {section_id!r} while resolving appendix ancestry."
                )
            if getattr(section, "kind", "section") == "appendix":
                appendix = appendix_by_label_element.get(section.element_id)
                if appendix is not None:
                    return ("appendix_record", appendix.appendix_id, appendix.label)

                label_element = element_by_id.get(section.element_id)
                if label_element is None:
                    raise CitationValidationError(
                        f"Appendix section {section.section_id!r} references missing label element {section.element_id!r}."
                    )
                if int(label_element.page_number) != int(section.page_number):
                    raise CitationValidationError(
                        f"Appendix section {section.section_id!r} page does not match its label element provenance."
                    )
                label = str(getattr(section, "title", "") or "").strip()
                if not label:
                    raise CitationValidationError(
                        f"Appendix section {section.section_id!r} has no deterministic label."
                    )
                return ("appendix_section", section.section_id, label)
            section_id = getattr(section, "parent_section_id", None) or ""
        return None

    # Prefer direct CanonicalElement.appendix_id, but deterministically recover
    # equivalent membership from explicit canonical parent-section ancestry when
    # needed. This intentionally never guesses appendix membership from pages.
    appendix_ref_by_source = {
        element_id: effective_appendix_ref(element_id)
        for element_id in source_element_ids
        if element_id in element_by_id
    }
    appendix_refs: list[tuple[str, str, str]] = []
    for ref in appendix_ref_by_source.values():
        if ref is not None and ref not in appendix_refs:
            appendix_refs.append(ref)

    for appendix_ref in appendix_refs:
        member_ids = [
            element_id for element_id in source_element_ids
            if appendix_ref_by_source.get(element_id) == appendix_ref
        ]
        member_pages = _ordered_unique_int(element_by_id[element_id].page_number for element_id in member_ids)
        locators.append({
            "kind": "appendix",
            "label": appendix_ref[2],
            "pages": member_pages,
            "source_element_ids": member_ids,
        })

    clause_records: list[ClauseRecord] = []
    for element_id in source_element_ids:
        record = clause_by_element.get(element_id)
        if record is not None and record not in clause_records:
            clause_records.append(record)
    clause_records.sort(key=lambda record: element_by_id[record.element_id].document_order)
    for record in clause_records:
        path = _clause_path(record, clause_by_id)
        label = f"Clause {path}" if path else f"Subclause {_marker_text(record.number)}"
        locators.append({
            "kind": record.kind,
            "label": label,
            "pages": [record.page_number],
            "source_element_ids": [record.element_id],
        })

    for definition in structure.definitions:
        definition_ids = _definition_source_ids(definition)
        overlap = [element_id for element_id in definition_ids if element_id in source_id_set]
        if not overlap:
            continue
        locator_pages = _ordered_unique_int(element_by_id[element_id].page_number for element_id in overlap if element_id in element_by_id)
        locators.append({
            "kind": "definition",
            "label": f"Definition “{definition.term}”",
            "pages": locator_pages or list(range(definition.start_page, definition.end_page + 1)),
            "source_element_ids": overlap,
        })

    # Clause/definition locators are already precise. Otherwise include the
    # canonical section containing the source. For appendix tables/figures/list
    # items, this preserves both the appendix label and a useful nested heading
    # such as ``REPORTING UPON DETERMINATION``.
    has_precise_content_locator = any(
        locator["kind"] in {"clause", "subclause", "definition"}
        for locator in locators
    )
    if not has_precise_content_locator:
        section_ids = _ordered_unique(
            element_by_id[element_id].section_id or ""
            for element_id in source_element_ids
            if element_id in element_by_id
        )
        for section_id in section_ids:
            section = section_by_id.get(section_id)
            if section is None:
                raise CitationValidationError(f"Canonical source references unknown section {section_id!r}.")
            # The appendix itself is already represented by the AppendixRecord
            # locator, so do not duplicate its section heading.
            if getattr(section, "kind", "section") == "appendix" and any(locator["kind"] == "appendix" for locator in locators):
                continue
            member_ids = [
                element_id for element_id in source_element_ids
                if element_by_id[element_id].section_id == section_id
            ]
            member_pages = _ordered_unique_int(element_by_id[element_id].page_number for element_id in member_ids)
            locators.append({
                "kind": "section",
                "label": section.title,
                "pages": member_pages,
                "source_element_ids": member_ids,
            })

    if not locators:
        locators.append({
            "kind": "page",
            "label": _page_text(pages),
            "pages": pages,
            "source_element_ids": list(source_element_ids),
        })

    # Remove identical locators while preserving canonical/document order.
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, tuple[int, ...]]] = set()
    for locator in locators:
        key = (locator["kind"], locator["label"], tuple(locator["pages"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(locator)
    return deduped


def _citation_display(locators: list[dict[str, Any]], pages: list[int]) -> str:
    structural = [locator["label"] for locator in locators if locator["kind"] != "page"]
    structural = _ordered_unique(structural)
    if structural:
        return " · ".join([*structural, _page_text(pages)])
    return _page_text(pages)


def build_citation_bundle(
    document_id: str,
    claims: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create final Stage 10 citations without asking the LLM for citation text."""

    if not claims:
        return {
            "claims": claims,
            "cited_answer": "",
            "citations": [],
            "citation_version": CITATION_VERSION,
            "citation_validation": {
                "status": "valid",
                "citation_count": 0,
                "valid_citation_count": 0,
                "errors": [],
            },
        }

    artifacts = validate_evidence_provenance(document_id, evidence)
    structure = artifacts.resolved.structure
    chunk_by_id = {chunk.chunk_id: chunk for chunk in artifacts.chunks.chunks}
    evidence_by_id = {str(row["evidence_id"]): row for row in evidence}

    used_evidence_ids: list[str] = []
    for claim in claims:
        for evidence_id in claim.get("evidence_ids", []):
            if evidence_id not in evidence_by_id:
                raise CitationValidationError(f"Claim references evidence ID {evidence_id!r} absent from citation input.")
            if evidence_id not in used_evidence_ids:
                used_evidence_ids.append(evidence_id)

    citations: list[dict[str, Any]] = []
    citation_id_by_evidence: dict[str, str] = {}
    marker_by_citation_id: dict[str, str] = {}
    for marker_number, evidence_id in enumerate(used_evidence_ids, start=1):
        row = evidence_by_id[evidence_id]
        chunk = chunk_by_id[str(row["chunk_id"])]
        pages = list(chunk.pages)
        source_element_ids = list(chunk.source_element_ids)
        locators = _source_locators(structure, source_element_ids, pages)

        # Final defensive validation: a rendered locator may only point to pages
        # and elements already present in the evidence's exact frozen chunk.
        for locator in locators:
            if not set(locator["pages"]).issubset(set(pages)):
                raise CitationValidationError(
                    f"Rendered locator {locator['label']!r} escapes {evidence_id} page provenance."
                )
            if not set(locator["source_element_ids"]).issubset(set(source_element_ids)):
                raise CitationValidationError(
                    f"Rendered locator {locator['label']!r} escapes {evidence_id} source-element provenance."
                )

        citation_id = f"CIT-{evidence_id}"
        marker = f"[{marker_number}]"
        citation_id_by_evidence[evidence_id] = citation_id
        marker_by_citation_id[citation_id] = marker
        citations.append({
            "citation_id": citation_id,
            "marker": marker,
            "evidence_id": evidence_id,
            "chunk_id": chunk.chunk_id,
            "chunk_index": chunk.chunk_index,
            "source_filename": structure.source_filename,
            "display": _citation_display(locators, pages),
            "pages": pages,
            "section_path": list(chunk.section_path),
            "source_element_ids": source_element_ids,
            "locators": locators,
            "validation_status": "valid",
        })

    enriched_claims: list[dict[str, Any]] = []
    cited_parts: list[str] = []
    for claim in claims:
        citation_ids = _ordered_unique(citation_id_by_evidence[evidence_id] for evidence_id in claim["evidence_ids"])
        enriched = {**claim, "citation_ids": citation_ids}
        enriched_claims.append(enriched)
        markers = "".join(marker_by_citation_id[citation_id] for citation_id in citation_ids)
        cited_parts.append(f"{claim['text'].strip()} {markers}".strip())

    return {
        "claims": enriched_claims,
        "cited_answer": " ".join(cited_parts).strip(),
        "citations": citations,
        "citation_version": CITATION_VERSION,
        "citation_validation": {
            "status": "valid",
            "citation_count": len(citations),
            "valid_citation_count": len(citations),
            "errors": [],
        },
    }
