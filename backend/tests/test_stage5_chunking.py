from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.config import settings
from app.main import app
from app.schemas import (
    CanonicalElement,
    CanonicalSourceTrace,
    ChunkingConfig,
    DefinitionEntry,
    DocumentClassification,
    DocumentRecord,
    LayoutEngineInfo,
    RelationshipIntegrityReport,
    RelationshipReviewState,
    ResolvedStructureArtifact,
    SectionRecord,
    StructuredDocument,
    StructuredPage,
    StructureSummary,
    StructuralRelation,
)
from app.services.chunking import ChunkingNotEligibleError, build_chunking_artifact
from app.services.storage import write_metadata, write_resolved_structure


def _source(index: int, *, page: int = 1) -> CanonicalSourceTrace:
    return CanonicalSourceTrace(
        layout_box_index=index,
        layout_box_class="text",
        stage3_block_ids=[f"p{page}-b{index + 1}"],
        stage3_line_ids=[f"p{page}-b{index + 1}-l1"],
        stage3_span_ids=[f"p{page}-b{index + 1}-l1-s1"],
        stage3_table_ids=[],
    )


def _element(
    element_id: str,
    type_: str,
    text: str,
    order: int,
    *,
    page: int = 1,
    bbox: list[float] | None = None,
    section_id: str | None = None,
    definition_entry_id: str | None = None,
) -> CanonicalElement:
    return CanonicalElement(
        element_id=element_id,
        type=type_,
        page_number=page,
        reading_order=order,
        document_order=order,
        bbox=bbox or [72, 100 + order * 40, 520, 130 + order * 40],
        text=text,
        section_id=section_id,
        definition_entry_id=definition_entry_id,
        role_source="test",
        source=_source(order, page=page),
    )


def _resolved(*, long_body: bool = False, integrity_status: str = "pass") -> ResolvedStructureArtifact:
    now = datetime.now(timezone.utc)
    section_id = "sec-1"
    header1 = _element("p1-e1", "page_header", "AML GUIDELINES", 0, bbox=[72, 20, 520, 40])
    section = _element("p1-e2", "section_header", "3 Definitions", 1, section_id=section_id)
    term = _element("p1-e3", "definition_term", "reporting institution", 2, section_id=section_id, definition_entry_id="def-1")
    definition = _element(
        "p1-e4",
        "definition_text",
        "means a person carrying on regulated activities under the applicable law.",
        3,
        section_id=section_id,
        definition_entry_id="def-1",
    )
    body_text = " ".join(f"word{i}" for i in range(500)) if long_body else "A reporting institution shall maintain appropriate records for the required period."
    body = _element("p1-e5", "paragraph", body_text, 4, section_id=section_id)
    footer = _element("p1-e6", "page_footer", "Page 1 of 2", 5, bbox=[72, 790, 520, 812])

    # A repeated margin text deliberately left as paragraph/unknown to verify
    # cleaning catches misclassified running content as well as explicit headers.
    repeated1 = _element("p1-e7", "paragraph", "CONFIDENTIAL COPY", 6, bbox=[72, 815, 520, 835])
    repeated2 = _element("p2-e1", "paragraph", "CONFIDENTIAL COPY", 7, page=2, bbox=[72, 815, 520, 835])
    repeated3 = _element("p3-e1", "paragraph", "CONFIDENTIAL COPY", 8, page=3, bbox=[72, 815, 520, 835])

    pages = [
        StructuredPage(page_number=1, width=595, height=842, elements=[header1, section, term, definition, body, footer, repeated1], body_text=""),
        StructuredPage(page_number=2, width=595, height=842, elements=[repeated2], body_text=""),
        StructuredPage(page_number=3, width=595, height=842, elements=[repeated3], body_text=""),
    ]
    structure = StructuredDocument(
        document_id="doc-stage5",
        source_filename="sample.pdf",
        source_sha256="sha-stage5",
        source_extraction_schema_version="1.1",
        layout_engine=LayoutEngineInfo(name="test", version="1"),
        title="AML Guidelines",
        title_source="test",
        metadata_element_ids=[],
        summary=StructureSummary(
            page_count=3,
            element_count=sum(len(page.elements) for page in pages),
            body_text_char_count=0,
            section_count=1,
            definition_count=1,
            element_counts={},
        ),
        sections=[SectionRecord(
            section_id=section_id,
            title="3 Definitions",
            level=1,
            page_number=1,
            element_id=section.element_id,
            content_element_ids=[term.element_id, definition.element_id, body.element_id],
        )],
        definitions=[DefinitionEntry(
            definition_id="def-1",
            term="reporting institution",
            section_id=section_id,
            term_element_id=term.element_id,
            definition_text=definition.text,
            definition_element_ids=[definition.element_id],
            start_page=1,
            end_page=1,
        )],
        clauses=[],
        appendices=[],
        tables=[],
        figures=[],
        relationships=[],
        pages=pages,
        body_text="",
        warnings=[],
        structured_at=now,
    )
    return ResolvedStructureArtifact(
        document_id=structure.document_id,
        source_sha256=structure.source_sha256,
        base_structured_at=structure.structured_at,
        correction_count=0,
        resolved_at=now,
        structure=structure,
        integrity=RelationshipIntegrityReport(status=integrity_status, semantic_status="clear" if integrity_status == "pass" else "blocked"),
        review=RelationshipReviewState(stage5_eligible=integrity_status == "pass"),
        warnings=[],
    )


def test_stage5_cleaning_is_auditable_and_keeps_section_as_context():
    artifact = build_chunking_artifact(resolved=_resolved())
    decisions = {decision.element_id: decision for decision in artifact.cleaning.decisions}

    assert decisions["p1-e1"].action == "exclude"
    assert decisions["p1-e1"].reason == "page_header"
    assert decisions["p1-e2"].action == "context"
    assert decisions["p1-e6"].reason == "page_footer"
    assert decisions["p1-e7"].reason == "repeated_margin_text"
    assert decisions["p2-e1"].reason == "repeated_margin_text"
    assert decisions["p3-e1"].reason == "repeated_margin_text"
    assert artifact.cleaning.excluded_element_count == 5
    assert artifact.cleaning.context_element_count == 1


def test_definition_term_and_text_form_one_semantic_chunk_with_provenance():
    artifact = build_chunking_artifact(resolved=_resolved())
    definition_chunks = [chunk for chunk in artifact.chunks if chunk.semantic_type == "definition"]
    assert len(definition_chunks) == 1
    chunk = definition_chunks[0]
    assert "reporting institution" in chunk.text
    assert "means a person carrying on regulated activities" in chunk.text
    assert chunk.section_path == ["3 Definitions"]
    assert chunk.source_element_ids == ["p1-e3", "p1-e4"]
    assert "p1-b3-l1-s1" in chunk.source_span_ids
    assert chunk.pages == [1]


def test_oversized_chunks_are_split_below_hard_max_and_ids_are_deterministic():
    resolved = _resolved(long_body=True)
    config = ChunkingConfig(target_tokens=100, max_tokens=150, overlap_tokens=20)
    first = build_chunking_artifact(resolved=resolved, config=config)
    second = build_chunking_artifact(resolved=resolved, config=config)

    assert first.summary.chunk_count > 2
    assert first.summary.max_chunk_tokens <= 150
    assert [chunk.chunk_id for chunk in first.chunks] == [chunk.chunk_id for chunk in second.chunks]
    split_chunks = [chunk for chunk in first.chunks if chunk.split_total]
    assert split_chunks
    assert all(chunk.split_part and chunk.split_total and chunk.split_part <= chunk.split_total for chunk in split_chunks)



def test_cross_page_definition_stays_one_semantic_unit():
    resolved = _resolved()
    structure = resolved.structure
    definition = next(element for element in structure.pages[0].elements if element.element_id == "p1-e4")
    structure.pages[0].elements.remove(definition)
    definition.page_number = 2
    definition.reading_order = 0
    definition.source = _source(3, page=2)
    structure.pages[1].elements.insert(0, definition)
    entry = structure.definitions[0]
    entry.end_page = 2
    entry.spans_multiple_pages = True

    artifact = build_chunking_artifact(resolved=resolved)
    chunks = [chunk for chunk in artifact.chunks if chunk.semantic_type == "definition"]
    assert len(chunks) == 1
    assert chunks[0].pages == [1, 2]
    assert chunks[0].source_element_ids == ["p1-e3", "p1-e4"]


def test_overlapping_duplicate_text_is_excluded_conservatively():
    resolved = _resolved()
    structure = resolved.structure
    duplicate = _element(
        "p1-e8",
        "paragraph",
        "A reporting institution shall maintain appropriate records for the required period.",
        9,
        section_id="sec-1",
        bbox=[72, 260, 520, 290],
    )
    original = next(element for element in structure.pages[0].elements if element.element_id == "p1-e5")
    duplicate.bbox = list(original.bbox)
    structure.pages[0].elements.append(duplicate)

    artifact = build_chunking_artifact(resolved=resolved)
    decisions = {decision.element_id: decision for decision in artifact.cleaning.decisions}
    assert decisions["p1-e5"].action == "include"
    assert decisions["p1-e8"].action == "exclude"
    assert decisions["p1-e8"].reason == "duplicate_overlapping_text"

def test_stage5_rejects_non_passing_resolved_structure():
    with pytest.raises(ChunkingNotEligibleError):
        build_chunking_artifact(resolved=_resolved(integrity_status="fail"))


def _prepare_dirs(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    for directory in (
        settings.raw_dir,
        settings.metadata_dir,
        settings.extracted_dir,
        settings.layout_dir,
        settings.structured_dir,
        settings.corrections_dir,
        settings.resolved_dir,
        settings.chunks_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def test_stage5_api_generate_fetch_and_reset(tmp_path: Path, monkeypatch):
    _prepare_dirs(tmp_path, monkeypatch)
    resolved = _resolved()
    now = datetime.now(timezone.utc)
    record = DocumentRecord(
        document_id=resolved.document_id,
        original_filename="sample.pdf",
        stored_filename=f"{resolved.document_id}.pdf",
        extension=".pdf",
        detected_mime_type="application/pdf",
        size_bytes=100,
        sha256=resolved.source_sha256,
        validation_status="valid",
        classification=DocumentClassification(document_family="pdf", pdf_type="digital", page_count=3),
        ingested_at=now,
        extraction_status="completed",
        structure_status="completed",
        structured_at=resolved.base_structured_at,
    )
    write_metadata(record)
    write_resolved_structure(resolved)

    client = TestClient(app)
    generated = client.post(f"/api/documents/{resolved.document_id}/chunks", json={"config": {}})
    assert generated.status_code == 200
    assert generated.json()["summary"]["chunk_count"] >= 2
    assert generated.json()["token_count_method"] == "regex_estimate_v1"

    fetched = client.get(f"/api/documents/{resolved.document_id}/chunks")
    assert fetched.status_code == 200
    assert fetched.json()["chunks"][0]["chunk_id"] == generated.json()["chunks"][0]["chunk_id"]

    reset = client.delete(f"/api/documents/{resolved.document_id}/chunks")
    assert reset.status_code == 204
    assert client.get(f"/api/documents/{resolved.document_id}/chunks").status_code == 404


def _resolved_with_hierarchy() -> ResolvedStructureArtifact:
    from app.schemas import ClauseRecord, StructuralRelation

    resolved = _resolved()
    structure = resolved.structure
    section_id = "sec-1"
    parent = _element("p1-e20", "clause", "8.1 A reporting institution must perform the following:", 20, section_id=section_id)
    parent.clause_number = "8.1"
    parent.clause_id = "clause-parent"
    child_a = _element("p1-e21", "subclause", "(a) identify the customer;", 21, section_id=section_id)
    child_a.subclause_marker = "(a)"
    child_a.clause_id = "clause-child-a"
    child_a.parent_clause_id = "clause-parent"
    child_b = _element("p1-e22", "subclause", "(b) verify the identity;", 22, section_id=section_id)
    child_b.subclause_marker = "(b)"
    child_b.clause_id = "clause-child-b"
    child_b.parent_clause_id = "clause-parent"
    child_c = _element("p1-e23", "subclause", "(c) understand the purpose of the relationship.", 23, section_id=section_id)
    child_c.subclause_marker = "(c)"
    child_c.clause_id = "clause-child-c"
    child_c.parent_clause_id = "clause-parent"
    structure.pages[0].elements.extend([parent, child_a, child_b, child_c])
    structure.sections[0].content_element_ids.extend([parent.element_id, child_a.element_id, child_b.element_id, child_c.element_id])
    structure.clauses.extend([
        ClauseRecord(clause_id="clause-parent", number="8.1", kind="clause", element_id=parent.element_id, page_number=1, section_id=section_id),
        ClauseRecord(clause_id="clause-child-a", number="(a)", kind="subclause", element_id=child_a.element_id, page_number=1, section_id=section_id, parent_clause_id="clause-parent"),
        ClauseRecord(clause_id="clause-child-b", number="(b)", kind="subclause", element_id=child_b.element_id, page_number=1, section_id=section_id, parent_clause_id="clause-parent"),
        ClauseRecord(clause_id="clause-child-c", number="(c)", kind="subclause", element_id=child_c.element_id, page_number=1, section_id=section_id, parent_clause_id="clause-parent"),
    ])
    structure.relationships.extend([
        StructuralRelation(relation_id="rel-parent-a", type="parent_of", source_element_id=parent.element_id, target_element_id=child_a.element_id, evidence="test hierarchy"),
        StructuralRelation(relation_id="rel-parent-b", type="parent_of", source_element_id=parent.element_id, target_element_id=child_b.element_id, evidence="test hierarchy"),
        StructuralRelation(relation_id="rel-parent-c", type="parent_of", source_element_id=parent.element_id, target_element_id=child_c.element_id, evidence="test hierarchy"),
    ])
    structure.summary.element_count += 4
    return resolved




def _resolved_generic_manual_hierarchy(*, long_children: bool = False) -> ResolvedStructureArtifact:
    """Synthetic non-AML policy document used to guard against domain overfitting."""
    from app.schemas import ClauseRecord, StructuralRelation

    resolved = _resolved()
    structure = resolved.structure
    # Remove AML-specific semantic records/content but keep generic page/header
    # fixtures required by the base helper.
    structure.title = "Employee Safety Manual"
    structure.sections[0].title = "4 Equipment shutdown procedure"
    section_id = structure.sections[0].section_id
    parent = _element("p1-g20", "clause", "4.1 Before maintenance, the technician must complete the following:", 20, section_id=section_id)
    parent.clause_number = "4.1"
    parent.clause_id = "g-parent"
    suffix = " " + " ".join(f"detail{i}" for i in range(120)) if long_children else ""
    children = []
    for offset, marker in enumerate(["(a)", "(b)", "(c)", "(d)"], start=21):
        child = _element(f"p1-g{offset}", "subclause", f"{marker} verify the assigned safety control{suffix};", offset, section_id=section_id)
        child.subclause_marker = marker
        child.clause_id = f"g-child-{marker}"
        child.parent_clause_id = "g-parent"
        children.append(child)
    structure.pages[0].elements.extend([parent, *children])
    structure.sections[0].content_element_ids.extend([parent.element_id, *(child.element_id for child in children)])
    structure.clauses.extend([
        ClauseRecord(clause_id="g-parent", number="4.1", kind="clause", element_id=parent.element_id, page_number=1, section_id=section_id),
        *[
            ClauseRecord(clause_id=child.clause_id, number=child.subclause_marker, kind="subclause", element_id=child.element_id, page_number=1, section_id=section_id, parent_clause_id="g-parent")
            for child in children
        ],
    ])
    structure.relationships.extend([
        StructuralRelation(relation_id=f"g-rel-{i}", type="parent_of", source_element_id=parent.element_id, target_element_id=child.element_id, evidence="synthetic hierarchy")
        for i, child in enumerate(children)
    ])
    structure.summary.element_count += 5
    return resolved


def test_semantic_v2_is_default_and_groups_generic_parent_with_children():
    artifact = build_chunking_artifact(resolved=_resolved_generic_manual_hierarchy())
    assert artifact.config.strategy == "semantic_v2"
    assert artifact.strategy_version == "semantic-v2.1"
    grouped = [chunk for chunk in artifact.chunks if "dependency_group" in chunk.refinement_tags]
    assert grouped
    chunk = grouped[0]
    assert "Before maintenance" in chunk.text
    assert "(a) verify the assigned safety control" in chunk.text
    assert "(d) verify the assigned safety control" in chunk.text
    assert chunk.context_element_ids == []
    assert artifact.quality.orphan_child_count == 0
    assert artifact.quality.dangling_intro_count == 0


def test_semantic_v2_splits_large_hierarchy_on_semantic_boundaries_and_repeats_parent_context():
    resolved = _resolved_generic_manual_hierarchy(long_children=True)
    config = ChunkingConfig(strategy="semantic_v2", soft_min_tokens=60, target_tokens=180, max_tokens=260, overlap_tokens=0)
    artifact = build_chunking_artifact(resolved=resolved, config=config)
    hierarchy = [chunk for chunk in artifact.chunks if "dependency_group" in chunk.refinement_tags]
    assert len(hierarchy) >= 2
    assert artifact.summary.max_chunk_tokens <= 260
    contextual = [chunk for chunk in hierarchy if "parent_context" in chunk.refinement_tags]
    assert contextual
    assert all("p1-g20" in chunk.context_element_ids for chunk in contextual)
    assert all("Parent context:" in chunk.context_text for chunk in contextual)
    assert artifact.quality.orphan_child_count == 0


def test_semantic_v2_excludes_generic_table_of_contents_navigation():
    from app.schemas import CanonicalTable, LogicalTable

    resolved = _resolved()
    structure = resolved.structure
    section_id = "sec-toc"
    toc_header = _element("p2-toc-h", "section_header", "Table of Contents", 30, page=2, section_id=section_id)
    toc = _element("p2-toc", "table", "", 31, page=2, section_id=section_id)
    toc.table = CanonicalTable(row_count=3, col_count=2, cells=[["Topic", "Page"], ["Installation", "3"], ["Operation", "9"]])
    structure.pages[1].elements.extend([toc_header, toc])
    structure.sections.append(SectionRecord(section_id=section_id, title="Table of Contents", level=1, page_number=2, element_id=toc_header.element_id, content_element_ids=[toc.element_id]))
    structure.tables.append(LogicalTable(logical_table_id="toc-table", fragment_element_ids=[toc.element_id], start_page=2, end_page=2, spans_multiple_pages=False, row_count=3, col_count=2, cells=toc.table.cells, section_id=section_id))
    artifact = build_chunking_artifact(resolved=resolved)
    decisions = {decision.element_id: decision for decision in artifact.cleaning.decisions}
    assert decisions[toc.element_id].action == "exclude"
    assert decisions[toc.element_id].reason == "navigation_only"
    assert not any(toc.element_id in chunk.source_element_ids for chunk in artifact.chunks)
    assert artifact.quality.navigation_chunk_count == 0


def test_semantic_v2_packs_short_standalone_sibling_clauses_conservatively():
    from app.schemas import ClauseRecord

    resolved = _resolved()
    structure = resolved.structure
    section_id = structure.sections[0].section_id
    clauses = []
    for i, text in enumerate([
        "5.1 Store the device indoors.",
        "5.2 Keep the device dry.",
        "5.3 Inspect the enclosure monthly.",
    ], start=40):
        element = _element(f"p1-s{i}", "clause", text, i, section_id=section_id)
        element.clause_number = text.split()[0]
        element.clause_id = f"s-{i}"
        clauses.append(element)
        structure.clauses.append(ClauseRecord(clause_id=element.clause_id, number=element.clause_number, kind="clause", element_id=element.element_id, page_number=1, section_id=section_id))
    structure.pages[0].elements.extend(clauses)
    artifact = build_chunking_artifact(resolved=resolved, config=ChunkingConfig(soft_min_tokens=80, target_tokens=180))
    packed = [chunk for chunk in artifact.chunks if "short_sibling_pack" in chunk.refinement_tags]
    assert packed
    assert all(text in packed[0].content_text for text in ["Store the device indoors", "Keep the device dry", "Inspect the enclosure monthly"])



def test_semantic_v2_merges_explicit_cross_page_continuations_generically():
    from app.schemas import StructuralRelation

    resolved = _resolved()
    structure = resolved.structure
    section_id = structure.sections[0].section_id
    first = _element("p1-cont", "paragraph", "The installation procedure continues on the next page", 60, section_id=section_id)
    second = _element("p2-cont", "paragraph", "with the final verification and sign-off steps.", 61, page=2, section_id=section_id)
    structure.pages[0].elements.append(first)
    structure.pages[1].elements.append(second)
    structure.relationships.append(StructuralRelation(relation_id="cont-generic", type="continues", source_element_id=first.element_id, target_element_id=second.element_id, evidence="cross-page continuation"))
    artifact = build_chunking_artifact(resolved=resolved)
    merged = [chunk for chunk in artifact.chunks if "continuation_merge" in chunk.refinement_tags]
    assert merged
    assert any(first.element_id in chunk.source_element_ids and second.element_id in chunk.source_element_ids for chunk in merged)
    assert any(chunk.pages == [1, 2] for chunk in merged)


def test_semantic_v2_attaches_confident_numbered_note_to_definition():
    resolved = _resolved()
    structure = resolved.structure
    # Re-purpose the base definition into an unrelated example with an inline
    # numbered note marker, matching the generic note rule.
    structure.definitions[0].term = "inspection interval"
    structure.definitions[0].definition_text = "means the scheduled2 maintenance period."
    term = next(e for e in structure.pages[0].elements if e.element_id == "p1-e3")
    definition = next(e for e in structure.pages[0].elements if e.element_id == "p1-e4")
    term.text = "inspection interval"
    definition.text = "means the scheduled2 maintenance period."
    body = next(e for e in structure.pages[0].elements if e.element_id == "p1-e5")
    structure.pages[0].elements.remove(body)
    structure.sections[0].content_element_ids = [element_id for element_id in structure.sections[0].content_element_ids if element_id != body.element_id]
    note = _element("p1-note", "paragraph", "2 Refers to the interval defined by the equipment manufacturer.", 4, section_id=structure.sections[0].section_id)
    structure.pages[0].elements.append(note)
    artifact = build_chunking_artifact(resolved=resolved)
    attached = [chunk for chunk in artifact.chunks if "note_attachment" in chunk.refinement_tags]
    assert attached
    assert "inspection interval" in attached[0].content_text
    assert "Note:" in attached[0].content_text
    assert note.element_id in attached[0].source_element_ids


def test_semantic_v2_splits_large_tables_between_rows_and_repeats_header_context():
    from app.schemas import CanonicalTable, LogicalTable

    resolved = _resolved()
    structure = resolved.structure
    section_id = structure.sections[0].section_id
    table_element = _element("p1-table-large", "table", "", 80, section_id=section_id)
    rows = [["Component", "Inspection requirement"]] + [
        [f"Component {i}", " ".join(["verify"] * 18)] for i in range(1, 9)
    ]
    table_element.table = CanonicalTable(row_count=len(rows), col_count=2, cells=rows)
    structure.pages[0].elements.append(table_element)
    structure.tables.append(LogicalTable(logical_table_id="generic-large-table", fragment_element_ids=[table_element.element_id], start_page=1, end_page=1, spans_multiple_pages=False, row_count=len(rows), col_count=2, cells=rows, section_id=section_id))
    artifact = build_chunking_artifact(resolved=resolved, config=ChunkingConfig(soft_min_tokens=40, target_tokens=100, max_tokens=150, overlap_tokens=0))
    table_chunks = [chunk for chunk in artifact.chunks if table_element.element_id in chunk.source_element_ids]
    assert len(table_chunks) >= 2
    assert all(chunk.token_count <= 150 for chunk in table_chunks)
    assert any("table_row_split" in chunk.refinement_tags for chunk in table_chunks[1:])
    assert any("Table header:" in chunk.context_text for chunk in table_chunks[1:])
    # A normal row should remain intact rather than being divided between chunks.
    assert any("Component 8" in chunk.content_text for chunk in table_chunks)


def test_stage5_has_no_agentic_or_provider_routes():
    client = TestClient(app)
    assert client.get("/api/documents/example/chunks/agentic/provider").status_code == 404
    assert client.post("/api/documents/example/chunks/agentic", json={"config": {}}).status_code == 404
    assert client.get("/api/documents/example/chunks/quality").status_code == 404


def test_stage5_backend_has_no_groq_dependency_or_settings():
    requirements = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "groq" not in requirements
    assert not hasattr(settings, "groq_api_key")
    assert not hasattr(settings, "groq_model")
    assert not hasattr(settings, "groq_base_url")
    assert not hasattr(settings, "groq_timeout_seconds")


def test_semantic_v2_groups_local_group_header_with_dependent_list_items():
    resolved = _resolved()
    structure = resolved.structure
    section_id = structure.sections[0].section_id
    start = max(element.document_order for page in structure.pages for element in page.elements) + 1
    clause = _element(
        "p1-group-clause", "clause",
        "4.2 The inspection applies to the following equipment types:",
        start, section_id=section_id,
    )
    clause.clause_number = "4.2"
    group = _element("p1-group-header", "group_header", "Equipment", start + 1, section_id=section_id)
    item_a = _element("p1-group-a", "list_item", "(a) Pumps;", start + 2, section_id=section_id)
    item_b = _element("p1-group-b", "list_item", "(b) Valves;", start + 3, section_id=section_id)
    structure.pages[0].elements.extend([clause, group, item_a, item_b])
    structure.relationships.extend([
        StructuralRelation(
            relation_id="rel-group-test-1", type="introduces",
            source_element_id=clause.element_id, target_element_id=group.element_id,
            evidence="fixture local group",
        ),
        StructuralRelation(
            relation_id="rel-group-test-2", type="introduces",
            source_element_id=group.element_id, target_element_id=item_a.element_id,
            evidence="fixture group member",
        ),
        StructuralRelation(
            relation_id="rel-group-test-3", type="introduces",
            source_element_id=group.element_id, target_element_id=item_b.element_id,
            evidence="fixture group member",
        ),
    ])
    structure.sections[0].content_element_ids.extend([clause.element_id, group.element_id, item_a.element_id, item_b.element_id])

    artifact = build_chunking_artifact(resolved=resolved, config=ChunkingConfig(strategy="semantic_v2"))
    matching = [chunk for chunk in artifact.chunks if group.element_id in chunk.context_element_ids]
    assert len(matching) == 1
    chunk = matching[0]
    assert group.element_id not in chunk.source_element_ids
    assert item_a.element_id in chunk.source_element_ids
    assert item_b.element_id in chunk.source_element_ids
    assert "Group: Equipment" in chunk.context_text
    assert "Equipment" not in chunk.content_text
    assert "Pumps" in chunk.content_text
    assert "Valves" in chunk.content_text
    assert "group_header_context" in chunk.refinement_tags
    assert artifact.quality.orphan_child_count == 0


def test_semantic_v2_excludes_toc_navigation_from_stage4_zone_signals_and_continuation_tables():
    from app.schemas import CanonicalTable, LogicalTable, SemanticClassification

    resolved = _resolved()
    structure = resolved.structure
    front_section = structure.sections[0].section_id
    next_order = max(element.document_order for page in structure.pages for element in page.elements) + 1

    toc_label = _element("p2-nav-label", "unknown", "CONTENTS", next_order, page=2)
    toc_label.role_source = "toc_navigation_suppression"
    toc_label.classification = SemanticClassification(
        selected_type="unknown",
        confidence=0.99,
        source="document_zone_resolver",
        evidence=["element occurs on a page identified as table-of-contents navigation"],
    )
    toc_table = _element("p2-nav-table", "table", "", next_order + 1, page=2, section_id=front_section)
    toc_table.table = CanonicalTable(
        row_count=3,
        col_count=3,
        cells=[["PART", "I: INTRODUCTION", "Page"], ["1.", "Introduction", "5"], ["2.", "Applicability", "6"]],
    )
    continuation = _element("p3-nav-table", "table", "", next_order + 2, page=3, section_id=front_section)
    continuation.table = CanonicalTable(
        row_count=3,
        col_count=3,
        cells=[["APPENDICES", "", "Page"], ["Appendix A:", "Guidance", "68"], ["Appendix B:", "Reference", "81"]],
    )
    structure.pages[1].elements.extend([toc_label, toc_table])
    structure.pages[2].elements.append(continuation)
    structure.tables.extend([
        LogicalTable(
            logical_table_id="toc-zone-table-1",
            fragment_element_ids=[toc_table.element_id],
            start_page=2,
            end_page=2,
            spans_multiple_pages=False,
            row_count=toc_table.table.row_count,
            col_count=toc_table.table.col_count,
            cells=toc_table.table.cells,
            section_id=front_section,
        ),
        LogicalTable(
            logical_table_id="toc-zone-table-2",
            fragment_element_ids=[continuation.element_id],
            start_page=3,
            end_page=3,
            spans_multiple_pages=False,
            row_count=continuation.table.row_count,
            col_count=continuation.table.col_count,
            cells=continuation.table.cells,
            section_id=front_section,
        ),
    ])

    artifact = build_chunking_artifact(resolved=resolved)
    decisions = {decision.element_id: decision for decision in artifact.cleaning.decisions}
    for element_id in [toc_label.element_id, toc_table.element_id, continuation.element_id]:
        assert decisions[element_id].action == "exclude"
        assert decisions[element_id].reason == "navigation_only"
        assert not any(element_id in chunk.source_element_ids for chunk in artifact.chunks)
    assert artifact.quality.navigation_chunk_count == 0
    assert artifact.quality.status == "pass"


def test_navigation_quality_gate_independently_detects_toc_leakage_when_cleaning_is_disabled():
    from app.schemas import CanonicalTable, LogicalTable

    resolved = _resolved()
    structure = resolved.structure
    section_id = structure.sections[0].section_id
    order = max(element.document_order for page in structure.pages for element in page.elements) + 1
    toc = _element("p2-quality-toc", "table", "", order, page=2, section_id=section_id)
    toc.table = CanonicalTable(
        row_count=4,
        col_count=3,
        cells=[["PART", "I: INTRODUCTION", "Page"], ["1.", "Introduction", "5"], ["2.", "Applicability", "6"], ["3.", "Definitions", "8"]],
    )
    structure.pages[1].elements.append(toc)
    structure.tables.append(LogicalTable(
        logical_table_id="quality-toc",
        fragment_element_ids=[toc.element_id],
        start_page=2,
        end_page=2,
        spans_multiple_pages=False,
        row_count=toc.table.row_count,
        col_count=toc.table.col_count,
        cells=toc.table.cells,
        section_id=section_id,
    ))

    artifact = build_chunking_artifact(
        resolved=resolved,
        config=ChunkingConfig(exclude_navigation_sections=False),
    )
    assert any(toc.element_id in chunk.source_element_ids for chunk in artifact.chunks)
    assert artifact.quality.navigation_chunk_count >= 1
    assert artifact.quality.status == "review"
    assert any(signal.code == "navigation_content" for signal in artifact.quality.signals)


def test_table_caption_is_owned_by_table_and_not_absorbed_by_previous_clause():
    from app.schemas import CanonicalTable, ClauseRecord, LogicalTable

    resolved = _resolved()
    structure = resolved.structure
    section_id = structure.sections[0].section_id
    order = max(element.document_order for page in structure.pages for element in page.elements) + 1

    clause = _element(
        "p1-caption-clause",
        "clause",
        "3.5 Consider the following example.",
        order,
        section_id=section_id,
    )
    clause.clause_number = "3.5"
    clause.clause_id = "caption-clause"
    caption = _element("p1-table-caption", "caption", "Example 1:", order + 1, section_id=section_id)
    table = _element("p1-caption-table", "table", "", order + 2, section_id=section_id)
    table.table = CanonicalTable(
        row_count=2,
        col_count=2,
        cells=[["Risk Factor", "Parameter"], ["Customer", "Risk rating"]],
    )
    structure.pages[0].elements.extend([clause, caption, table])
    structure.clauses.append(ClauseRecord(
        clause_id=clause.clause_id,
        number=clause.clause_number,
        kind="clause",
        element_id=clause.element_id,
        page_number=1,
        section_id=section_id,
    ))
    structure.tables.append(LogicalTable(
        logical_table_id="caption-table",
        fragment_element_ids=[table.element_id],
        start_page=1,
        end_page=1,
        spans_multiple_pages=False,
        row_count=table.table.row_count,
        col_count=table.table.col_count,
        cells=table.table.cells,
        section_id=section_id,
    ))

    artifact = build_chunking_artifact(resolved=resolved)
    clause_chunk = next(chunk for chunk in artifact.chunks if clause.element_id in chunk.source_element_ids)
    table_chunk = next(chunk for chunk in artifact.chunks if table.element_id in chunk.source_element_ids)

    assert caption.element_id not in clause_chunk.source_element_ids
    assert "Example 1:" not in clause_chunk.content_text
    assert table_chunk.semantic_type == "table"
    assert table_chunk.source_element_ids == [caption.element_id, table.element_id]
    assert table_chunk.content_text.startswith("Example 1:\n\nRisk Factor | Parameter")
    assert "caption_attachment" in table_chunk.refinement_tags
    assert not any(
        chunk.semantic_type == "caption" and caption.element_id in chunk.source_element_ids
        for chunk in artifact.chunks
    )


def test_semantic_v2_attaches_consecutive_group_headers_as_context_without_topk_only_header_chunks():
    from app.schemas import ClauseRecord

    resolved = _resolved()
    structure = resolved.structure
    section_id = structure.sections[0].section_id
    order = max(element.document_order for page in structure.pages for element in page.elements) + 1

    group_outer = _element(
        "p1-local-group-outer",
        "group_header",
        "CDD requirements for individual customer and beneficial owner",
        order,
        section_id=section_id,
    )
    group_inner = _element(
        "p1-local-group-inner",
        "group_header",
        "Identification and Verification",
        order + 1,
        section_id=section_id,
    )
    clause_a = _element(
        "p1-local-clause-a",
        "clause",
        "8.1.1 A reporting institution must identify and verify the customer before establishing the relationship.",
        order + 2,
        section_id=section_id,
    )
    clause_a.clause_id = "local-clause-a"
    clause_a.clause_number = "8.1.1"

    next_group = _element(
        "p1-local-group-next",
        "group_header",
        "Delayed verification",
        order + 3,
        section_id=section_id,
    )
    clause_b = _element(
        "p1-local-clause-b",
        "clause",
        "8.1.2 A reporting institution may complete verification later only where the stated safeguards are satisfied.",
        order + 4,
        section_id=section_id,
    )
    clause_b.clause_id = "local-clause-b"
    clause_b.clause_number = "8.1.2"

    structure.pages[0].elements.extend([group_outer, group_inner, clause_a, next_group, clause_b])
    structure.sections[0].content_element_ids.extend(
        [group_outer.element_id, group_inner.element_id, clause_a.element_id, next_group.element_id, clause_b.element_id]
    )
    structure.clauses.extend([
        ClauseRecord(
            clause_id=clause_a.clause_id,
            number=clause_a.clause_number,
            kind="clause",
            element_id=clause_a.element_id,
            page_number=1,
            section_id=section_id,
        ),
        ClauseRecord(
            clause_id=clause_b.clause_id,
            number=clause_b.clause_number,
            kind="clause",
            element_id=clause_b.element_id,
            page_number=1,
            section_id=section_id,
        ),
    ])

    artifact = build_chunking_artifact(resolved=resolved)
    first_chunk = next(chunk for chunk in artifact.chunks if clause_a.element_id in chunk.source_element_ids)
    second_chunk = next(chunk for chunk in artifact.chunks if clause_b.element_id in chunk.source_element_ids)

    assert group_outer.element_id not in first_chunk.source_element_ids
    assert group_inner.element_id not in first_chunk.source_element_ids
    assert first_chunk.context_element_ids == [group_outer.element_id, group_inner.element_id]
    assert (
        "Group: CDD requirements for individual customer and beneficial owner > Identification and Verification"
        in first_chunk.context_text
    )
    assert "group_header_context" in first_chunk.refinement_tags

    assert second_chunk.context_element_ids == [next_group.element_id]
    assert "Group: Delayed verification" in second_chunk.context_text
    assert group_outer.element_id not in second_chunk.context_element_ids
    assert group_inner.element_id not in second_chunk.context_element_ids

    header_ids = {group_outer.element_id, group_inner.element_id, next_group.element_id}
    assert not any(header_ids & set(chunk.source_element_ids) for chunk in artifact.chunks)
    assert artifact.quality.group_header_context_chunk_count >= 2
    assert artifact.quality.standalone_group_header_chunk_count == 0


def test_semantic_v2_suppresses_intro_only_figure_but_keeps_explained_figure():
    from app.schemas import FigureRecord

    resolved = _resolved()
    structure = resolved.structure
    section_id = structure.sections[0].section_id
    order = max(element.document_order for page in structure.pages for element in page.elements) + 1

    intro = _element(
        "p1-figure-intro-only",
        "paragraph",
        "The workflow above is illustrated in the diagram below:",
        order,
        section_id=section_id,
    )
    empty_figure = _element(
        "p1-figure-empty",
        "figure",
        "",
        order + 1,
        section_id=section_id,
    )
    caption = _element(
        "p1-figure-caption",
        "caption",
        "Illustration 2",
        order + 2,
        section_id=section_id,
    )
    explained_figure = _element(
        "p1-figure-explained",
        "figure",
        "",
        order + 3,
        section_id=section_id,
    )
    explanation = _element(
        "p1-figure-explanation",
        "paragraph",
        "The diagram shows that the senior manager is treated as the beneficial owner when no other person has effective control.",
        order + 4,
        section_id=section_id,
    )

    structure.pages[0].elements.extend([intro, empty_figure, caption, explained_figure, explanation])
    structure.sections[0].content_element_ids.extend(
        [intro.element_id, empty_figure.element_id, caption.element_id, explained_figure.element_id, explanation.element_id]
    )
    structure.figures.extend([
        FigureRecord(
            figure_id="figure-intro-only",
            element_id=empty_figure.element_id,
            page_number=1,
            section_id=section_id,
            intro_element_ids=[intro.element_id],
        ),
        FigureRecord(
            figure_id="figure-explained",
            element_id=explained_figure.element_id,
            page_number=1,
            section_id=section_id,
            caption_element_ids=[caption.element_id],
            explanation_element_ids=[explanation.element_id],
        ),
    ])

    artifact = build_chunking_artifact(resolved=resolved)
    decisions = {decision.element_id: decision for decision in artifact.cleaning.decisions}

    assert decisions[intro.element_id].action == "context"
    assert decisions[intro.element_id].reason == "figure_intro_context_only"
    assert not any(intro.element_id in chunk.source_element_ids for chunk in artifact.chunks)
    assert not any(
        chunk.semantic_type == "figure" and intro.element_id in chunk.source_element_ids
        for chunk in artifact.chunks
    )

    useful = next(
        chunk for chunk in artifact.chunks
        if chunk.semantic_type == "figure" and caption.element_id in chunk.source_element_ids
    )
    assert "Illustration 2" in useful.content_text
    assert "senior manager is treated as the beneficial owner" in useful.content_text
    assert explanation.element_id in useful.source_element_ids
    assert artifact.quality.intro_only_figure_chunk_count == 0
    assert artifact.quality.status == "pass"


def test_semantic_v2_group_header_context_crosses_descendant_section_but_not_document_root():
    from app.schemas import ClauseRecord, StructuralRelation

    resolved = _resolved()
    structure = resolved.structure
    root_id = structure.sections[0].section_id
    order = max(element.document_order for page in structure.pages for element in page.elements) + 1

    group = _element(
        "p1-root-group",
        "group_header",
        "Appendix implementation guidance",
        order,
        section_id=root_id,
    )
    child_header = _element(
        "p1-child-header",
        "section_header",
        "1.0 Introduction",
        order + 1,
        section_id="sec-child",
    )
    child_clause = _element(
        "p1-child-clause",
        "clause",
        "1.1 This child section contains the guidance body.",
        order + 2,
        section_id="sec-child",
    )
    child_clause.clause_id = "child-clause"
    child_clause.clause_number = "1.1"

    root2_header = _element(
        "p1-root2-header",
        "section_header",
        "APPENDIX B",
        order + 3,
        section_id="sec-root-2",
    )
    root2_clause = _element(
        "p1-root2-clause",
        "clause",
        "1.1 This belongs to a different document root.",
        order + 4,
        section_id="sec-root-2",
    )
    root2_clause.clause_id = "root2-clause"
    root2_clause.clause_number = "1.1"

    structure.pages[0].elements.extend([group, child_header, child_clause, root2_header, root2_clause])
    structure.sections.extend([
        SectionRecord(
            section_id="sec-child",
            title="1.0 Introduction",
            level=2,
            page_number=1,
            element_id=child_header.element_id,
            parent_section_id=root_id,
            content_element_ids=[child_clause.element_id],
        ),
        SectionRecord(
            section_id="sec-root-2",
            title="APPENDIX B",
            level=1,
            page_number=1,
            element_id=root2_header.element_id,
            content_element_ids=[root2_clause.element_id],
        ),
    ])
    structure.relationships.append(StructuralRelation(
        relation_id="rel-group-child-section",
        type="introduces",
        source_element_id=group.element_id,
        target_element_id=child_header.element_id,
        evidence="group explicitly scopes the following outline section",
    ))
    structure.clauses.extend([
        ClauseRecord(
            clause_id=child_clause.clause_id,
            number=child_clause.clause_number,
            kind="clause",
            element_id=child_clause.element_id,
            page_number=1,
            section_id="sec-child",
        ),
        ClauseRecord(
            clause_id=root2_clause.clause_id,
            number=root2_clause.clause_number,
            kind="clause",
            element_id=root2_clause.element_id,
            page_number=1,
            section_id="sec-root-2",
        ),
    ])

    artifact = build_chunking_artifact(resolved=resolved)
    child_chunk = next(chunk for chunk in artifact.chunks if child_clause.element_id in chunk.source_element_ids)
    root2_chunk = next(chunk for chunk in artifact.chunks if root2_clause.element_id in chunk.source_element_ids)

    assert group.element_id in child_chunk.context_element_ids
    assert "Group: Appendix implementation guidance" in child_chunk.context_text
    assert group.element_id not in root2_chunk.context_element_ids
    assert "Appendix implementation guidance" not in root2_chunk.context_text


def test_semantic_v2_group_header_context_uses_section_tree_fallback_when_resolved_introduces_edge_missing():
    """Resolved Stage 4.5 may retain hierarchy while omitting a redundant local edge."""

    resolved = _resolved()
    structure = resolved.structure
    root_id = structure.sections[0].section_id
    order = max(element.document_order for page in structure.pages for element in page.elements) + 1

    group = _element(
        "p1-appendix-form-title",
        "group_header",
        "MEASURES PURSUANT TO THE STRATEGIC TRADE REGULATIONS",
        order,
        section_id=root_id,
    )
    child_header = _element(
        "p1-reporting-header",
        "section_header",
        "REPORTING UPON DETERMINATION",
        order + 1,
        section_id="sec-reporting",
    )
    child_body = _element(
        "p1-reporting-body",
        "paragraph",
        "UNSCR Number (If Available): Date of UN Listing:",
        order + 2,
        section_id="sec-reporting",
    )

    structure.pages[0].elements.extend([group, child_header, child_body])
    structure.sections.extend([
        SectionRecord(
            section_id="sec-reporting",
            title="REPORTING UPON DETERMINATION",
            level=2,
            page_number=1,
            element_id=child_header.element_id,
            parent_section_id=root_id,
            content_element_ids=[child_body.element_id],
        )
    ])
    structure.sections[0].content_element_ids.append(group.element_id)

    # Intentionally do NOT add group -> section ``introduces``. This reproduces
    # resolved artifacts where the hierarchy survives but the redundant edge does not.
    artifact = build_chunking_artifact(resolved=resolved)

    body_chunk = next(chunk for chunk in artifact.chunks if child_body.element_id in chunk.source_element_ids)
    assert group.element_id in body_chunk.context_element_ids
    assert "Group: MEASURES PURSUANT TO THE STRATEGIC TRADE REGULATIONS" in body_chunk.context_text
    assert not any(
        chunk.semantic_type == "group_header" and group.element_id in chunk.source_element_ids
        for chunk in artifact.chunks
    )
    assert artifact.quality.standalone_group_header_chunk_count == 0


def test_semantic_v2_suppresses_non_explanatory_figure_shell_but_keeps_informative_intro():
    from app.schemas import FigureRecord

    resolved = _resolved()
    structure = resolved.structure
    section_id = structure.sections[0].section_id
    order = max(element.document_order for page in structure.pages for element in page.elements) + 1

    shell_intro = _element(
        "p1-shell-intro",
        "paragraph",
        "An overview of the due diligence process is set out in Illustration 1 below.",
        order,
        section_id=section_id,
    )
    shell_figure = _element("p1-shell-figure", "figure", "", order + 1, section_id=section_id)
    shell_caption = _element("p1-shell-caption", "caption", "Illustration 1:", order + 2, section_id=section_id)
    shell_source = _element(
        "p1-shell-source",
        "paragraph",
        "For full FATF Guidance and Source for Illustration 1: Updated Guidance for Risk-Based Approach - Virtual Assets and Virtual Asset Service Providers.",
        order + 3,
        section_id=section_id,
    )

    informative_intro = _element(
        "p1-informative-intro",
        "paragraph",
        "The diagram establishes that all high-risk customers require enhanced due diligence and senior management approval.",
        order + 4,
        section_id=section_id,
    )
    informative_figure = _element("p1-informative-figure", "figure", "", order + 5, section_id=section_id)
    informative_caption = _element("p1-informative-caption", "caption", "Illustration 2", order + 6, section_id=section_id)
    informative_source = _element(
        "p1-informative-source",
        "paragraph",
        "Source: FATF Guidance.",
        order + 7,
        section_id=section_id,
    )

    new_elements = [
        shell_intro,
        shell_figure,
        shell_caption,
        shell_source,
        informative_intro,
        informative_figure,
        informative_caption,
        informative_source,
    ]
    structure.pages[0].elements.extend(new_elements)
    structure.sections[0].content_element_ids.extend(element.element_id for element in new_elements)
    structure.figures.extend([
        FigureRecord(
            figure_id="figure-shell",
            element_id=shell_figure.element_id,
            page_number=1,
            section_id=section_id,
            intro_element_ids=[shell_intro.element_id],
            caption_element_ids=[shell_caption.element_id],
            source_element_ids=[shell_source.element_id],
        ),
        FigureRecord(
            figure_id="figure-informative-intro",
            element_id=informative_figure.element_id,
            page_number=1,
            section_id=section_id,
            intro_element_ids=[informative_intro.element_id],
            caption_element_ids=[informative_caption.element_id],
            source_element_ids=[informative_source.element_id],
        ),
    ])

    artifact = build_chunking_artifact(resolved=resolved)
    decisions = {decision.element_id: decision for decision in artifact.cleaning.decisions}

    for element_id in [shell_intro.element_id, shell_caption.element_id, shell_source.element_id]:
        assert decisions[element_id].action == "context"
        assert decisions[element_id].reason == "figure_non_explanatory_context_only"
        assert not any(element_id in chunk.source_element_ids for chunk in artifact.chunks)

    assert not any(
        chunk.semantic_type == "figure"
        and shell_caption.element_id in chunk.source_element_ids
        for chunk in artifact.chunks
    )

    informative_chunk = next(
        chunk
        for chunk in artifact.chunks
        if chunk.semantic_type == "figure"
        and informative_caption.element_id in chunk.source_element_ids
    )
    assert "all high-risk customers require enhanced due diligence" in informative_chunk.content_text
    assert informative_intro.element_id in informative_chunk.source_element_ids
    assert informative_source.element_id in informative_chunk.source_element_ids

    assert artifact.quality.non_explanatory_figure_chunk_count == 0
    assert artifact.quality.status == "pass"


def test_semantic_v2_local_group_context_stops_before_unrelated_numbered_clause_and_packing_respects_group_boundaries():
    from app.schemas import ClauseRecord, StructuralRelation

    resolved = _resolved()
    structure = resolved.structure
    section_id = structure.sections[0].section_id
    order = max(element.document_order for page in structure.pages for element in page.elements) + 1

    intro_clause = _element(
        "p1-rba-intro",
        "clause",
        "2.1 The assessment has two local components:",
        order,
        section_id=section_id,
    )
    intro_clause.clause_id = "rba-intro"
    intro_clause.clause_number = "2.1"

    bb_group = _element("p1-bbra-group", "group_header", "Business-based Risk Assessment (BbRA)", order + 1, section_id=section_id)
    bb_body = _element(
        "p1-bbra-body",
        "paragraph",
        "In a BbRA, a reporting institution identifies business-level ML/TF/PF risks.",
        order + 2,
        section_id=section_id,
    )
    bb_item = _element(
        "p1-bbra-item",
        "list_item",
        "I. Perform the business risk assessment.",
        order + 3,
        section_id=section_id,
    )

    rb_group = _element("p1-rbra-group", "group_header", "Relationship-based Risk Assessment (RbRA)", order + 4, section_id=section_id)
    rb_body = _element(
        "p1-rbra-body",
        "paragraph",
        "In a RbRA, a reporting institution considers customer-level risk factors.",
        order + 5,
        section_id=section_id,
    )
    rb_item = _element(
        "p1-rbra-item",
        "list_item",
        "I. Determine customer risk parameters.",
        order + 6,
        section_id=section_id,
    )

    next_clause = _element(
        "p1-next-rba-clause",
        "clause",
        "2.2 The RBA must be tailored to the institution's business, size and activities.",
        order + 7,
        section_id=section_id,
    )
    next_clause.clause_id = "rba-next"
    next_clause.clause_number = "2.2"

    new_elements = [intro_clause, bb_group, bb_body, bb_item, rb_group, rb_body, rb_item, next_clause]
    structure.pages[0].elements.extend(new_elements)
    structure.sections[0].content_element_ids.extend(element.element_id for element in new_elements)
    structure.clauses.extend([
        ClauseRecord(
            clause_id=intro_clause.clause_id,
            number=intro_clause.clause_number,
            kind="clause",
            element_id=intro_clause.element_id,
            page_number=1,
            section_id=section_id,
        ),
        ClauseRecord(
            clause_id=next_clause.clause_id,
            number=next_clause.clause_number,
            kind="clause",
            element_id=next_clause.element_id,
            page_number=1,
            section_id=section_id,
        ),
    ])
    structure.relationships.extend([
        StructuralRelation(
            relation_id="rel-bbra-body",
            type="introduces",
            source_element_id=bb_group.element_id,
            target_element_id=bb_body.element_id,
            evidence="local group body",
        ),
        StructuralRelation(
            relation_id="rel-rbra-body",
            type="introduces",
            source_element_id=rb_group.element_id,
            target_element_id=rb_body.element_id,
            evidence="local group body",
        ),
    ])

    artifact = build_chunking_artifact(resolved=resolved)

    bb_chunk = next(chunk for chunk in artifact.chunks if bb_body.element_id in chunk.source_element_ids)
    rb_chunk = next(chunk for chunk in artifact.chunks if rb_body.element_id in chunk.source_element_ids)
    next_chunk = next(chunk for chunk in artifact.chunks if next_clause.element_id in chunk.source_element_ids)

    assert bb_group.element_id in bb_chunk.context_element_ids
    assert rb_group.element_id not in bb_chunk.context_element_ids
    assert "Group: Business-based Risk Assessment (BbRA)" in bb_chunk.context_text
    assert "Relationship-based Risk Assessment" not in bb_chunk.context_text

    assert rb_group.element_id in rb_chunk.context_element_ids
    assert bb_group.element_id not in rb_chunk.context_element_ids
    assert "Group: Relationship-based Risk Assessment (RbRA)" in rb_chunk.context_text
    assert "Business-based Risk Assessment" not in rb_chunk.context_text

    # The next independent numbered clause is outside both local groups.
    assert bb_group.element_id not in next_chunk.context_element_ids
    assert rb_group.element_id not in next_chunk.context_element_ids
    assert "Business-based Risk Assessment" not in next_chunk.context_text
    assert "Relationship-based Risk Assessment" not in next_chunk.context_text

    # Generic packing must not merge units carrying different group contexts.
    assert bb_chunk.chunk_id != rb_chunk.chunk_id
    assert not any(
        bb_group.element_id in chunk.context_element_ids and rb_group.element_id in chunk.context_element_ids
        for chunk in artifact.chunks
    )
