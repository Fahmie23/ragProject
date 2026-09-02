from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services import citations


NOW = datetime(2026, 9, 2, tzinfo=timezone.utc)


def _element(
    element_id: str,
    *,
    page: int,
    order: int,
    section_id: str = "sec-8-1",
    appendix_id: str | None = None,
):
    return SimpleNamespace(
        element_id=element_id,
        page_number=page,
        document_order=order,
        section_id=section_id,
        appendix_id=appendix_id,
    )


def _artifacts(
    *,
    source_ids: list[str] | None = None,
    pages: list[int] | None = None,
    clauses: list[SimpleNamespace] | None = None,
    appendices: list[SimpleNamespace] | None = None,
    definitions: list[SimpleNamespace] | None = None,
    elements: list[SimpleNamespace] | None = None,
):
    source_ids = source_ids or ["e-clause"]
    pages = pages or [38]
    elements = elements or [_element("e-clause", page=38, order=1)]
    clauses = clauses if clauses is not None else [
        SimpleNamespace(
            clause_id="clause-1",
            number="8.1.25",
            kind="clause",
            element_id="e-clause",
            page_number=38,
            section_id="sec-8-1",
            parent_clause_id=None,
        )
    ]
    structure = SimpleNamespace(
        source_filename="sc_aml_cft_guidelines.pdf",
        pages=[SimpleNamespace(elements=elements)],
        clauses=clauses,
        appendices=appendices or [],
        definitions=definitions or [],
        sections=[SimpleNamespace(section_id="sec-8-1", title="8.1 CDD")],
    )
    resolved = SimpleNamespace(
        document_id="doc",
        source_sha256="sha",
        resolved_at=NOW,
        structure=structure,
    )
    chunk = SimpleNamespace(
        chunk_id="chunk-1",
        chunk_index=101,
        pages=pages,
        section_path=["PART III", "8. CUSTOMER DUE DILIGENCE", "8.1 CDD"],
        source_element_ids=source_ids,
    )
    chunking = SimpleNamespace(
        document_id="doc",
        source_sha256="sha",
        source_resolved_at=NOW,
        chunks=[chunk],
    )
    return citations.CitationArtifacts(resolved=resolved, chunks=chunking)


def _evidence(*, pages: list[int] | None = None, source_ids: list[str] | None = None):
    return [{
        "evidence_id": "E1",
        "chunk_id": "chunk-1",
        "chunk_index": 101,
        "pages": pages or [38],
        "section_path": ["PART III", "8. CUSTOMER DUE DILIGENCE", "8.1 CDD"],
        "source_element_ids": source_ids or ["e-clause"],
    }]


def test_clause_citation_is_derived_from_frozen_chunk_and_canonical_structure(monkeypatch):
    monkeypatch.setattr(citations, "_load_artifacts", lambda document_id: _artifacts())

    bundle = citations.build_citation_bundle(
        "doc",
        [{"claim_id": "C1", "text": "Delayed verification has conditions.", "evidence_ids": ["E1"]}],
        _evidence(),
    )

    citation = bundle["citations"][0]
    assert citation["citation_id"] == "CIT-E1"
    assert citation["marker"] == "[1]"
    assert citation["display"] == "Clause 8.1.25 · PDF p. 38"
    assert citation["pages"] == [38]
    assert citation["source_element_ids"] == ["e-clause"]
    assert citation["validation_status"] == "valid"
    assert bundle["claims"][0]["citation_ids"] == ["CIT-E1"]
    assert bundle["cited_answer"] == "Delayed verification has conditions. [1]"


def test_nested_subclause_and_appendix_are_rendered_without_llm_citation_text(monkeypatch):
    elements = [
        _element("e-main", page=83, order=1, section_id="sec-app-b", appendix_id="appendix-b"),
        _element("e-sub-a", page=83, order=2, section_id="sec-app-b", appendix_id="appendix-b"),
        _element("e-sub-i", page=83, order=3, section_id="sec-app-b", appendix_id="appendix-b"),
    ]
    clauses = [
        SimpleNamespace(clause_id="c-main", number="1.11", kind="clause", element_id="e-main", page_number=83, section_id="sec-app-b", parent_clause_id=None),
        SimpleNamespace(clause_id="c-a", number="(a)", kind="subclause", element_id="e-sub-a", page_number=83, section_id="sec-app-b", parent_clause_id="c-main"),
        SimpleNamespace(clause_id="c-i", number="(i)", kind="subclause", element_id="e-sub-i", page_number=83, section_id="sec-app-b", parent_clause_id="c-a"),
    ]
    appendix = SimpleNamespace(appendix_id="appendix-b", label="APPENDIX B")
    artifacts = _artifacts(
        source_ids=["e-main", "e-sub-a", "e-sub-i"],
        pages=[83],
        clauses=clauses,
        appendices=[appendix],
        elements=elements,
    )
    artifacts.resolved.structure.sections = [SimpleNamespace(section_id="sec-app-b", title="Applicable CDD Measures")]
    monkeypatch.setattr(citations, "_load_artifacts", lambda document_id: artifacts)
    evidence = [{
        "evidence_id": "E1", "chunk_id": "chunk-1", "chunk_index": 101, "pages": [83],
        "section_path": ["APPENDIX B", "Applicable CDD Measures"],
        "source_element_ids": ["e-main", "e-sub-a", "e-sub-i"],
    }]
    # Make the frozen chunk section path exactly match this evidence.
    artifacts.chunks.chunks[0].section_path = list(evidence[0]["section_path"])

    bundle = citations.build_citation_bundle(
        "doc",
        [{"claim_id": "C1", "text": "The measure applies.", "evidence_ids": ["E1"]}],
        evidence,
    )
    display = bundle["citations"][0]["display"]
    assert "APPENDIX B" in display
    assert "Clause 1.11(a)(i)" in display
    assert "PDF p. 83" in display


def test_appendix_ancestry_recovers_appendix_for_nested_table_without_direct_appendix_id(monkeypatch):
    elements = [
        _element("e-app-label", page=107, order=1, section_id="sec-app-i", appendix_id="appendix-i"),
        _element("e-report-heading", page=107, order=2, section_id="sec-report", appendix_id="appendix-i"),
        _element("e-table", page=107, order=3, section_id="sec-report", appendix_id=None),
    ]
    appendix = SimpleNamespace(
        appendix_id="appendix-i",
        label="APPENDIX I",
        label_element_id="e-app-label",
    )
    artifacts = _artifacts(
        source_ids=["e-table"],
        pages=[107],
        clauses=[],
        appendices=[appendix],
        elements=elements,
    )
    artifacts.resolved.structure.sections = [
        SimpleNamespace(
            section_id="sec-app-i",
            title="APPENDIX I",
            kind="appendix",
            element_id="e-app-label",
            parent_section_id=None,
        ),
        SimpleNamespace(
            section_id="sec-report",
            title="REPORTING UPON DETERMINATION",
            kind="section",
            element_id="e-report-heading",
            parent_section_id="sec-app-i",
        ),
    ]
    artifacts.chunks.chunks[0].section_path = ["APPENDIX I", "REPORTING UPON DETERMINATION"]
    monkeypatch.setattr(citations, "_load_artifacts", lambda document_id: artifacts)
    evidence = [{
        "evidence_id": "E1",
        "chunk_id": "chunk-1",
        "chunk_index": 101,
        "pages": [107],
        "section_path": ["APPENDIX I", "REPORTING UPON DETERMINATION"],
        "source_element_ids": ["e-table"],
    }]

    bundle = citations.build_citation_bundle(
        "doc",
        [{"claim_id": "C1", "text": "Appendix I contains the reporting table.", "evidence_ids": ["E1"]}],
        evidence,
    )

    citation = bundle["citations"][0]
    assert citation["display"] == "APPENDIX I · REPORTING UPON DETERMINATION · PDF p. 107"
    assert [locator["kind"] for locator in citation["locators"]] == ["appendix", "section"]
    assert citation["locators"][0]["source_element_ids"] == ["e-table"]
    assert citation["locators"][1]["source_element_ids"] == ["e-table"]
    assert bundle["citation_version"] == "deterministic_citations_v1_2"


def test_appendix_section_is_authoritative_when_appendix_record_is_absent(monkeypatch):
    elements = [
        _element("e-app-label", page=107, order=1, section_id="sec-app-i", appendix_id=None),
        _element("e-report-heading", page=107, order=2, section_id="sec-report", appendix_id=None),
        _element("e-table", page=107, order=3, section_id="sec-report", appendix_id=None),
    ]
    artifacts = _artifacts(
        source_ids=["e-table"],
        pages=[107],
        clauses=[],
        appendices=[],
        elements=elements,
    )
    artifacts.resolved.structure.sections = [
        SimpleNamespace(
            section_id="sec-app-i",
            title="APPENDIX I",
            kind="appendix",
            element_id="e-app-label",
            page_number=107,
            parent_section_id=None,
        ),
        SimpleNamespace(
            section_id="sec-report",
            title="REPORTING UPON DETERMINATION",
            kind="section",
            element_id="e-report-heading",
            page_number=107,
            parent_section_id="sec-app-i",
        ),
    ]
    artifacts.chunks.chunks[0].section_path = ["APPENDIX I", "REPORTING UPON DETERMINATION"]
    monkeypatch.setattr(citations, "_load_artifacts", lambda document_id: artifacts)
    evidence = [{
        "evidence_id": "E1",
        "chunk_id": "chunk-1",
        "chunk_index": 101,
        "pages": [107],
        "section_path": ["APPENDIX I", "REPORTING UPON DETERMINATION"],
        "source_element_ids": ["e-table"],
    }]

    bundle = citations.build_citation_bundle(
        "doc",
        [{"claim_id": "C1", "text": "Appendix I contains the reporting table.", "evidence_ids": ["E1"]}],
        evidence,
    )

    citation = bundle["citations"][0]
    assert citation["display"] == "APPENDIX I · REPORTING UPON DETERMINATION · PDF p. 107"
    assert [locator["kind"] for locator in citation["locators"]] == ["appendix", "section"]
    assert bundle["citation_version"] == "deterministic_citations_v1_2"


def test_appendix_section_fallback_still_rejects_missing_label_element(monkeypatch):
    elements = [
        _element("e-table", page=107, order=3, section_id="sec-report", appendix_id=None),
    ]
    artifacts = _artifacts(
        source_ids=["e-table"],
        pages=[107],
        clauses=[],
        appendices=[],
        elements=elements,
    )
    artifacts.resolved.structure.sections = [
        SimpleNamespace(
            section_id="sec-app-i",
            title="APPENDIX I",
            kind="appendix",
            element_id="missing-app-label",
            page_number=107,
            parent_section_id=None,
        ),
        SimpleNamespace(
            section_id="sec-report",
            title="REPORTING UPON DETERMINATION",
            kind="section",
            element_id="missing-report-heading",
            page_number=107,
            parent_section_id="sec-app-i",
        ),
    ]
    artifacts.chunks.chunks[0].section_path = ["APPENDIX I", "REPORTING UPON DETERMINATION"]
    monkeypatch.setattr(citations, "_load_artifacts", lambda document_id: artifacts)
    evidence = [{
        "evidence_id": "E1",
        "chunk_id": "chunk-1",
        "chunk_index": 101,
        "pages": [107],
        "section_path": ["APPENDIX I", "REPORTING UPON DETERMINATION"],
        "source_element_ids": ["e-table"],
    }]

    with pytest.raises(citations.CitationValidationError, match="missing label element"):
        citations.build_citation_bundle(
            "doc",
            [{"claim_id": "C1", "text": "Appendix I contains the reporting table.", "evidence_ids": ["E1"]}],
            evidence,
        )


def test_definition_citation_uses_definition_record(monkeypatch):
    element = _element("e-def", page=13, order=1, section_id="sec-def")
    definition = SimpleNamespace(
        term="politically exposed person (PEP)",
        term_element_id="e-def",
        source_table_element_id=None,
        definition_element_ids=[],
        start_page=13,
        end_page=13,
    )
    artifacts = _artifacts(source_ids=["e-def"], pages=[13], clauses=[], definitions=[definition], elements=[element])
    artifacts.resolved.structure.sections = [SimpleNamespace(section_id="sec-def", title="3. DEFINITIONS")]
    artifacts.chunks.chunks[0].section_path = ["3. DEFINITIONS"]
    monkeypatch.setattr(citations, "_load_artifacts", lambda document_id: artifacts)
    evidence = [{
        "evidence_id": "E1", "chunk_id": "chunk-1", "chunk_index": 101, "pages": [13],
        "section_path": ["3. DEFINITIONS"], "source_element_ids": ["e-def"],
    }]

    bundle = citations.build_citation_bundle(
        "doc",
        [{"claim_id": "C1", "text": "A PEP has prominent public functions.", "evidence_ids": ["E1"]}],
        evidence,
    )
    assert bundle["citations"][0]["display"] == "Definition “politically exposed person (PEP)” · PDF p. 13"


def test_provenance_rejects_page_mismatch(monkeypatch):
    monkeypatch.setattr(citations, "_load_artifacts", lambda document_id: _artifacts())
    with pytest.raises(citations.CitationValidationError, match="pages do not match"):
        citations.build_citation_bundle(
            "doc",
            [{"claim_id": "C1", "text": "Claim.", "evidence_ids": ["E1"]}],
            _evidence(pages=[39]),
        )


def test_provenance_rejects_source_element_mismatch(monkeypatch):
    monkeypatch.setattr(citations, "_load_artifacts", lambda document_id: _artifacts())
    with pytest.raises(citations.CitationValidationError, match="source_element_ids do not match"):
        citations.build_citation_bundle(
            "doc",
            [{"claim_id": "C1", "text": "Claim.", "evidence_ids": ["E1"]}],
            _evidence(source_ids=["invented-element"]),
        )


def test_stale_stage5_chunk_artifact_is_rejected(monkeypatch):
    artifacts = _artifacts()
    artifacts.chunks.source_resolved_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(citations, "read_resolved_structure", lambda document_id: artifacts.resolved)
    monkeypatch.setattr(citations, "read_chunking_artifact", lambda document_id: artifacts.chunks)
    with pytest.raises(citations.CitationValidationError, match="stale"):
        citations.validate_evidence_provenance("doc", _evidence())


def test_citation_markers_follow_first_claim_use_not_evidence_number(monkeypatch):
    e1 = _element("e1", page=10, order=1)
    e2 = _element("e2", page=11, order=2)
    artifacts = _artifacts(source_ids=["e1"], pages=[10], elements=[e1], clauses=[
        SimpleNamespace(clause_id="c1", number="1.1", kind="clause", element_id="e1", page_number=10, section_id="sec-8-1", parent_clause_id=None),
    ])
    artifacts.chunks.chunks.append(SimpleNamespace(
        chunk_id="chunk-2", chunk_index=102, pages=[11], section_path=["PART III", "8. CUSTOMER DUE DILIGENCE", "8.1 CDD"], source_element_ids=["e2"]
    ))
    artifacts.resolved.structure.pages[0].elements.append(e2)
    artifacts.resolved.structure.clauses.append(
        SimpleNamespace(clause_id="c2", number="1.2", kind="clause", element_id="e2", page_number=11, section_id="sec-8-1", parent_clause_id=None)
    )
    monkeypatch.setattr(citations, "_load_artifacts", lambda document_id: artifacts)
    evidence = [
        {**_evidence(pages=[10], source_ids=["e1"])[0], "evidence_id": "E1", "chunk_id": "chunk-1"},
        {**_evidence(pages=[11], source_ids=["e2"])[0], "evidence_id": "E2", "chunk_id": "chunk-2", "chunk_index": 102},
    ]
    claims = [
        {"claim_id": "C1", "text": "Second chunk first.", "evidence_ids": ["E2"]},
        {"claim_id": "C2", "text": "First chunk second.", "evidence_ids": ["E1"]},
    ]

    bundle = citations.build_citation_bundle("doc", claims, evidence)
    assert [(item["evidence_id"], item["marker"]) for item in bundle["citations"]] == [("E2", "[1]"), ("E1", "[2]")]
    assert bundle["claims"][0]["citation_ids"] == ["CIT-E2"]
    assert bundle["claims"][1]["citation_ids"] == ["CIT-E1"]


def test_abstention_needs_no_citation_artifacts(monkeypatch):
    def explode(document_id):
        raise AssertionError("citation source should not be loaded for an answer with no claims")
    monkeypatch.setattr(citations, "_load_artifacts", explode)
    bundle = citations.build_citation_bundle("doc", [], _evidence())
    assert bundle["citations"] == []
    assert bundle["citation_validation"]["status"] == "valid"
