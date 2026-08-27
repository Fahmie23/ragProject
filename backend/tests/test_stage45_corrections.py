from datetime import datetime, timezone
from pathlib import Path

import pymupdf
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.schemas import (
    CanonicalElement,
    CanonicalSourceTrace,
    CanonicalTable,
    ClauseRecord,
    AppendixRecord,
    CorrectionArtifact,
    CorrectionElementSpec,
    CorrectionOperation,
    CorrectionRelationshipSpec,
    CorrectionStructureSpec,
    DocumentClassification,
    DocumentExtraction,
    DocumentRecord,
    DefinitionEntry,
    ExtractionSummary,
    ExtractorInfo,
    FigureRecord,
    LogicalTable,
    PageExtraction,
    StructuralRelation,
    StructuredPage,
    SectionRecord,
    TextBlock,
    TextLine,
    TextSpan,
)
from app.services.canonical import build_canonical_document
from app.services.corrections import resolve_structure


def _text_block(block_id: str, number: int, bbox: list[float], text: str, size: float = 11) -> TextBlock:
    # Split at newline so Stage 4.5 can deterministically assign text after a bbox split.
    y0 = bbox[1]
    line_height = max((bbox[3] - bbox[1]) / max(len(text.splitlines()), 1), 8)
    lines = []
    for index, part in enumerate(text.splitlines() or [text]):
        line_bbox = [bbox[0], y0 + index * line_height, bbox[2], min(bbox[3], y0 + (index + 1) * line_height)]
        span = TextSpan(text=part, bbox=line_bbox, font="Test", size=size)
        lines.append(TextLine(bbox=line_bbox, text=part, spans=[span]))
    return TextBlock(block_id=block_id, number=number, bbox=bbox, text=text, lines=lines)


def _fixture():
    now = datetime.now(timezone.utc)
    record = DocumentRecord(
        document_id="doc-45",
        original_filename="sample.pdf",
        stored_filename="doc-45.pdf",
        extension=".pdf",
        detected_mime_type="application/pdf",
        size_bytes=100,
        sha256="sha45",
        validation_status="valid",
        classification=DocumentClassification(
            document_family="pdf", pdf_type="digital", page_count=1,
            text_pages=1, image_pages=0, has_text_layer=True, has_images=False, encrypted=False,
        ),
        ingested_at=now,
        extraction_status="completed",
        extracted_at=now,
        structure_status="completed",
    )
    extraction = DocumentExtraction(
        document_id="doc-45",
        source_filename="sample.pdf",
        source_sha256="sha45",
        source_pdf_type="digital",
        extraction_mode="text_layer",
        extractor=ExtractorInfo(name="PyMuPDF", version="test"),
        summary=ExtractionSummary(page_count=1, text_char_count=60, text_block_count=2, image_block_count=0, table_count=0),
        pages=[PageExtraction(
            page_number=1, width=600, height=800, rotation=0,
            text="Running Header\nFigure 2: Risk Based Approach\nBody paragraph",
            text_char_count=60,
            blocks=[
                _text_block("p1-b1", 1, [60, 30, 540, 100], "Running Header\nFigure 2: Risk Based Approach"),
                _text_block("p1-b2", 2, [60, 140, 540, 180], "Body paragraph"),
            ],
            tables=[], warnings=[],
        )],
        warnings=[], extracted_at=now,
    )
    layout = {
        "engine": {"name": "PyMuPDF4LLM Layout", "version": "test", "settings": {"use_layout": True, "use_ocr": False}},
        "result": {
            "filename": "sample.pdf", "page_count": 1, "toc": [],
            "pages": [{
                "page_number": 1, "width": 600, "height": 800,
                "boxes": [
                    {"x0": 60, "y0": 30, "x1": 540, "y1": 100, "boxclass": "page-header", "textlines": [
                        {"spans": [{"text": "Running Header"}]},
                        {"spans": [{"text": "Figure 2: Risk Based Approach"}]},
                    ]},
                    {"x0": 60, "y0": 140, "x1": 540, "y1": 180, "boxclass": "text", "textlines": [{"spans": [{"text": "Body paragraph"}]}]},
                ],
            }],
        },
    }
    structure = build_canonical_document(record=record, extraction=extraction, layout_artifact=layout)
    record.structured_at = structure.structured_at
    return record, extraction, structure


def test_split_header_into_header_and_caption_rebuilds_text_from_stage3():
    _, extraction, structure = _fixture()
    op = CorrectionOperation(
        operation_id="op-split",
        operation="split",
        page_number=1,
        source_element_ids=["p1-e1"],
        result_elements=[
            CorrectionElementSpec(element_id="manual-header", type="page_header", bbox=[60, 30, 540, 63]),
            CorrectionElementSpec(element_id="manual-caption", type="caption", bbox=[60, 63, 540, 102]),
        ],
        created_at=datetime.now(timezone.utc),
    )
    artifact = CorrectionArtifact(
        document_id=structure.document_id,
        source_sha256=structure.source_sha256,
        base_structure_schema_version=structure.schema_version,
        base_structured_at=structure.structured_at,
        operations=[op],
        updated_at=datetime.now(timezone.utc),
    )
    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=artifact)
    page = resolved.structure.pages[0]
    assert [item.type for item in page.elements][:2] == ["page_header", "caption"]
    assert page.elements[0].text == "Running Header"
    assert page.elements[1].text == "Figure 2: Risk Based Approach"
    assert "Running Header" not in page.body_text
    assert "Figure 2: Risk Based Approach" in page.body_text
    assert resolved.correction_count == 1


def test_move_resize_and_relabel_apply_sequentially():
    _, extraction, structure = _fixture()
    operations = [
        CorrectionOperation(
            operation_id="op-box", operation="move_resize", page_number=1,
            source_element_ids=["p1-e2"],
            result_elements=[CorrectionElementSpec(element_id="p1-e2", type="paragraph", bbox=[55, 135, 545, 185])],
            created_at=datetime.now(timezone.utc),
        ),
        CorrectionOperation(
            operation_id="op-label", operation="relabel", page_number=1,
            source_element_ids=["p1-e2"], new_type="caption",
            created_at=datetime.now(timezone.utc),
        ),
    ]
    artifact = CorrectionArtifact(
        document_id=structure.document_id, source_sha256=structure.source_sha256,
        base_structure_schema_version=structure.schema_version, base_structured_at=structure.structured_at,
        operations=operations, updated_at=datetime.now(timezone.utc),
    )
    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=artifact)
    item = next(item for item in resolved.structure.pages[0].elements if item.element_id == "p1-e2")
    assert item.type == "caption"
    assert item.bbox == [55.0, 135.0, 545.0, 185.0]
    assert item.text == "Body paragraph"


def test_bulk_relabel_applies_one_semantic_type_to_selected_elements():
    _, extraction, structure = _fixture()
    source_ids = [element.element_id for element in structure.pages[0].elements]
    operation = CorrectionOperation(
        operation_id="op-bulk-relabel",
        operation="relabel",
        page_number=1,
        source_element_ids=source_ids,
        new_type="paragraph",
        created_at=datetime.now(timezone.utc),
    )
    artifact = CorrectionArtifact(
        document_id=structure.document_id,
        source_sha256=structure.source_sha256,
        base_structure_schema_version=structure.schema_version,
        base_structured_at=structure.structured_at,
        operations=[operation],
        updated_at=datetime.now(timezone.utc),
    )

    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=artifact)
    assert [element.type for element in resolved.structure.pages[0].elements] == ["paragraph", "paragraph"]
    assert resolved.correction_count == 1


def test_manual_definition_link_rebuilds_definition_entry():
    _, extraction, structure = _fixture()
    term = structure.pages[0].elements[0]
    definition_text = structure.pages[0].elements[1]
    term.type = "definition_term"
    term.definition_entry_id = None
    term.heading_level = None
    term.heading_level_source = None
    definition_text.type = "definition_text"
    definition_text.definition_entry_id = None

    operation = CorrectionOperation(
        operation_id="op-definition-link",
        operation="link_definition",
        page_number=1,
        source_element_ids=[term.element_id, definition_text.element_id],
        note="manual term-to-definition link",
        created_at=datetime.now(timezone.utc),
    )
    artifact = CorrectionArtifact(
        document_id=structure.document_id,
        source_sha256=structure.source_sha256,
        base_structure_schema_version=structure.schema_version,
        base_structured_at=structure.structured_at,
        operations=[operation],
        updated_at=datetime.now(timezone.utc),
    )

    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=artifact)
    resolved_term = resolved.structure.pages[0].elements[0]
    resolved_text = resolved.structure.pages[0].elements[1]
    assert resolved_term.definition_entry_id == resolved_text.definition_entry_id
    assert resolved_term.definition_entry_id.startswith("manual-def-")
    assert len(resolved.structure.definitions) == 1
    entry = resolved.structure.definitions[0]
    assert entry.term_element_id == resolved_term.element_id
    assert entry.definition_element_ids == [resolved_text.element_id]
    assert entry.term == resolved_term.text
    assert entry.definition_text == resolved_text.text


def test_manual_definition_unlink_removes_definition_entry_when_last_text_is_removed():
    _, extraction, structure = _fixture()
    term = structure.pages[0].elements[0]
    definition_text = structure.pages[0].elements[1]
    term.type = "definition_term"
    term.definition_entry_id = None
    term.heading_level = None
    term.heading_level_source = None
    definition_text.type = "definition_text"
    definition_text.definition_entry_id = None

    operations = [
        CorrectionOperation(
            operation_id="op-definition-link",
            operation="link_definition",
            page_number=1,
            source_element_ids=[term.element_id, definition_text.element_id],
            created_at=datetime.now(timezone.utc),
        ),
        CorrectionOperation(
            operation_id="op-definition-unlink",
            operation="unlink_definition",
            page_number=1,
            source_element_ids=[term.element_id, definition_text.element_id],
            created_at=datetime.now(timezone.utc),
        ),
    ]
    artifact = CorrectionArtifact(
        document_id=structure.document_id,
        source_sha256=structure.source_sha256,
        base_structure_schema_version=structure.schema_version,
        base_structured_at=structure.structured_at,
        operations=operations,
        updated_at=datetime.now(timezone.utc),
    )

    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=artifact)
    resolved_term = resolved.structure.pages[0].elements[0]
    resolved_text = resolved.structure.pages[0].elements[1]
    assert resolved_term.definition_entry_id is None
    assert resolved_text.definition_entry_id is None
    assert resolved.structure.definitions == []


def test_manual_definition_link_rejects_wrong_semantic_types():
    _, extraction, structure = _fixture()
    operation = CorrectionOperation(
        operation_id="op-definition-link-invalid",
        operation="link_definition",
        page_number=1,
        source_element_ids=[structure.pages[0].elements[0].element_id, structure.pages[0].elements[1].element_id],
        created_at=datetime.now(timezone.utc),
    )
    artifact = CorrectionArtifact(
        document_id=structure.document_id,
        source_sha256=structure.source_sha256,
        base_structure_schema_version=structure.schema_version,
        base_structured_at=structure.structured_at,
        operations=[operation],
        updated_at=datetime.now(timezone.utc),
    )

    import pytest
    from app.services.corrections import InvalidCorrectionError

    with pytest.raises(InvalidCorrectionError, match="definition_term"):
        resolve_structure(automatic=structure, extraction=extraction, corrections=artifact)


def _cross_page_fixture():
    _, extraction, structure = _fixture()
    extraction = extraction.model_copy(deep=True)
    structure = structure.model_copy(deep=True)

    extraction.pages.append(PageExtraction(
        page_number=2,
        width=600,
        height=800,
        rotation=0,
        text="Continuation item",
        text_char_count=len("Continuation item"),
        blocks=[_text_block("p2-b1", 1, [80, 80, 520, 120], "Continuation item")],
        tables=[],
        warnings=[],
    ))
    extraction.summary.page_count = 2

    target = CanonicalElement(
        element_id="p2-e1",
        type="list_item",
        page_number=2,
        reading_order=0,
        document_order=2,
        bbox=[80, 80, 520, 120],
        text="Continuation item",
        role_source="test fixture",
        source=CanonicalSourceTrace(
            layout_box_index=-1,
            layout_box_class="text",
            stage3_block_ids=["p2-b1"],
            stage3_table_ids=[],
        ),
    )
    structure.pages.append(StructuredPage(
        page_number=2,
        width=600,
        height=800,
        elements=[target],
        body_text="Continuation item",
    ))
    structure.summary.page_count = 2
    structure.summary.element_count += 1
    structure.body_text = f"{structure.body_text}\n\nContinuation item"
    return extraction, structure


def test_manual_cross_page_relationship_can_be_added():
    extraction, structure = _cross_page_fixture()
    operation = CorrectionOperation(
        operation_id="op-link",
        operation="add_relationship",
        page_number=1,
        relationships=[CorrectionRelationshipSpec(
            relation_id="manual-rel-1",
            type="continues",
            source_element_id="p1-e2",
            target_element_id="p2-e1",
            source_page_number=1,
            target_page_number=2,
            evidence="manual cross-page continuation",
        )],
        created_at=datetime.now(timezone.utc),
    )
    artifact = CorrectionArtifact(
        document_id=structure.document_id,
        source_sha256=structure.source_sha256,
        base_structure_schema_version=structure.schema_version,
        base_structured_at=structure.structured_at,
        operations=[operation],
        updated_at=datetime.now(timezone.utc),
    )

    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=artifact)
    relation = next(item for item in resolved.structure.relationships if item.relation_id == "manual-rel-1")
    assert relation.type == "continues"
    assert relation.source_element_id == "p1-e2"
    assert relation.target_element_id == "p2-e1"
    assert "manual" in relation.evidence
    assert resolved.structure.summary.relation_count == len(resolved.structure.relationships)


def test_manual_cross_page_relationship_can_remove_automatic_link():
    extraction, structure = _cross_page_fixture()
    structure.relationships.append(StructuralRelation(
        relation_id="auto-rel-1",
        type="continues",
        source_element_id="p1-e2",
        target_element_id="p2-e1",
        evidence="automatic cross-page hierarchy",
    ))
    structure.summary.relation_count = len(structure.relationships)

    operation = CorrectionOperation(
        operation_id="op-unlink",
        operation="remove_relationship",
        page_number=1,
        relationships=[CorrectionRelationshipSpec(
            relation_id="auto-rel-1",
            type="continues",
            source_element_id="p1-e2",
            target_element_id="p2-e1",
            source_page_number=1,
            target_page_number=2,
            evidence="automatic cross-page hierarchy",
        )],
        created_at=datetime.now(timezone.utc),
    )
    artifact = CorrectionArtifact(
        document_id=structure.document_id,
        source_sha256=structure.source_sha256,
        base_structure_schema_version=structure.schema_version,
        base_structured_at=structure.structured_at,
        operations=[operation],
        updated_at=datetime.now(timezone.utc),
    )

    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=artifact)
    assert all(item.relation_id != "auto-rel-1" for item in resolved.structure.relationships)


def test_manual_continues_relationship_must_point_forward():
    extraction, structure = _cross_page_fixture()
    operation = CorrectionOperation(
        operation_id="op-backward",
        operation="add_relationship",
        page_number=2,
        relationships=[CorrectionRelationshipSpec(
            relation_id="manual-rel-backward",
            type="continues",
            source_element_id="p2-e1",
            target_element_id="p1-e2",
            source_page_number=2,
            target_page_number=1,
        )],
        created_at=datetime.now(timezone.utc),
    )
    artifact = CorrectionArtifact(
        document_id=structure.document_id,
        source_sha256=structure.source_sha256,
        base_structure_schema_version=structure.schema_version,
        base_structured_at=structure.structured_at,
        operations=[operation],
        updated_at=datetime.now(timezone.utc),
    )

    import pytest
    from app.services.corrections import InvalidCorrectionError

    with pytest.raises(InvalidCorrectionError, match="point forward"):
        resolve_structure(automatic=structure, extraction=extraction, corrections=artifact)


def _pdf_bytes() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((60, 50), "Running Header", fontsize=11)
    page.insert_text((60, 85), "Figure 2: Risk Based Approach", fontsize=11)
    page.insert_text((60, 150), "Body paragraph", fontsize=11)
    payload = doc.tobytes()
    doc.close()
    return payload


def _layout_artifact() -> dict:
    return {
        "engine": {"name": "PyMuPDF4LLM Layout", "version": "test", "settings": {"use_layout": True, "use_ocr": False}},
        "result": {"filename": "sample.pdf", "page_count": 1, "toc": [], "pages": [{
            "page_number": 1, "width": 600, "height": 800,
            "boxes": [
                {"x0": 50, "y0": 30, "x1": 550, "y1": 105, "boxclass": "page-header", "textlines": [
                    {"spans": [{"text": "Running Header"}]}, {"spans": [{"text": "Figure 2: Risk Based Approach"}]},
                ]},
                {"x0": 50, "y0": 130, "x1": 550, "y1": 180, "boxclass": "text", "textlines": [{"spans": [{"text": "Body paragraph"}]}]},
            ],
        }]},
    }


def _prepare_dirs(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    for directory in (
        settings.raw_dir, settings.metadata_dir, settings.extracted_dir, settings.layout_dir,
        settings.structured_dir, settings.corrections_dir, settings.resolved_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def test_correction_api_persists_resolved_and_stage4_rerun_invalidates(tmp_path: Path, monkeypatch):
    _prepare_dirs(tmp_path, monkeypatch)
    monkeypatch.setattr("app.services.structure.analyze_pdf_layout", lambda path: _layout_artifact())
    client = TestClient(app)
    upload = client.post("/api/documents/upload", files={"file": ("sample.pdf", _pdf_bytes(), "application/pdf")})
    document_id = upload.json()["document"]["document_id"]
    assert client.post(f"/api/documents/{document_id}/extract").status_code == 200
    structure_response = client.post(f"/api/documents/{document_id}/structure")
    assert structure_response.status_code == 200
    structure = structure_response.json()

    request = {
        "base_structured_at": structure["structured_at"],
        "operations": [{
            "operation_id": "op-relabel",
            "operation": "relabel",
            "page_number": 1,
            "source_element_ids": ["p1-e2"],
            "result_elements": [],
            "new_type": "caption",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }],
    }
    saved = client.put(f"/api/documents/{document_id}/corrections", json=request)
    assert saved.status_code == 200, saved.text
    assert saved.json()["resolved"]["correction_count"] == 1
    assert client.get(f"/api/documents/{document_id}/corrections").status_code == 200
    assert client.get(f"/api/documents/{document_id}/resolved-structure").status_code == 200

    saved_payload = saved.json()
    assert saved_payload["resolved"]["review"]["stage5_eligible"] is True
    approval = client.post(
        f"/api/documents/{document_id}/corrections/approve-relationships",
        json={
            "base_structured_at": structure["structured_at"],
            "correction_updated_at": saved_payload["corrections"]["updated_at"],
            "approved_issue_ids": [
                issue["issue_id"] for issue in saved_payload["resolved"]["integrity"]["warnings"] if issue["requires_review"]
            ],
            "note": "reviewed for Stage 5",
        },
    )
    assert approval.status_code == 200, approval.text
    assert approval.json()["resolved"]["review"]["status"] == "approved"
    assert approval.json()["resolved"]["review"]["stage5_eligible"] is True

    # A later save clears legacy approval metadata, but Stage 5 readiness is
    # still automatic as long as blocking integrity checks pass.
    resaved = client.put(f"/api/documents/{document_id}/corrections", json=request)
    assert resaved.status_code == 200, resaved.text
    assert resaved.json()["resolved"]["review"]["status"] == "not_reviewed"
    assert resaved.json()["resolved"]["review"]["stage5_eligible"] is True

    # Re-running Stage 4 invalidates the manual layer because automatic element IDs may change.
    assert client.post(f"/api/documents/{document_id}/structure").status_code == 200
    assert client.get(f"/api/documents/{document_id}/corrections").status_code == 404
    assert client.get(f"/api/documents/{document_id}/resolved-structure").status_code == 404


def _artifact_for(structure, operations):
    return CorrectionArtifact(
        document_id=structure.document_id,
        source_sha256=structure.source_sha256,
        base_structure_schema_version=structure.schema_version,
        base_structured_at=structure.structured_at,
        operations=operations,
        updated_at=datetime.now(timezone.utc),
    )


def test_split_rejects_duplicate_result_ids():
    _, extraction, structure = _fixture()
    source = structure.pages[0].elements[1]
    operation = CorrectionOperation(
        operation_id="op-duplicate-split", operation="split", page_number=1,
        source_element_ids=[source.element_id],
        result_elements=[
            CorrectionElementSpec(element_id="dup", type="paragraph", bbox=[60, 140, 540, 160]),
            CorrectionElementSpec(element_id="dup", type="paragraph", bbox=[60, 160, 540, 180]),
        ], created_at=datetime.now(timezone.utc),
    )
    import pytest
    from app.services.corrections import InvalidCorrectionError
    with pytest.raises(InvalidCorrectionError, match="unique"):
        resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))


def test_split_assigns_boundary_crossing_span_to_only_one_result():
    _, extraction, structure = _fixture()
    source = structure.pages[0].elements[1]
    operation = CorrectionOperation(
        operation_id="op-single-line-split", operation="split", page_number=1,
        source_element_ids=[source.element_id],
        result_elements=[
            CorrectionElementSpec(element_id="split-a", type="paragraph", bbox=[60, 140, 540, 160]),
            CorrectionElementSpec(element_id="split-b", type="paragraph", bbox=[60, 160, 540, 180]),
        ], created_at=datetime.now(timezone.utc),
    )
    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))
    texts = [item.text for item in resolved.structure.pages[0].elements if item.element_id in {"split-a", "split-b"}]
    assert texts.count("Body paragraph") == 1
    assert texts.count("") == 1
    assert resolved.structure.pages[0].body_text.count("Body paragraph") == 1


def test_merge_rejects_non_contiguous_selection_that_would_duplicate_middle_content():
    _, extraction, structure = _fixture()
    extraction = extraction.model_copy(deep=True)
    structure = structure.model_copy(deep=True)
    extraction.pages[0].blocks = [
        _text_block("p1-b1", 1, [60, 100, 540, 130], "A"),
        _text_block("p1-b2", 2, [60, 140, 540, 170], "B"),
        _text_block("p1-b3", 3, [60, 180, 540, 210], "C"),
    ]
    structure.pages[0].elements = [
        CanonicalElement(element_id="a", type="paragraph", page_number=1, reading_order=0, document_order=0, bbox=[60,100,540,130], text="A", role_source="test", source=CanonicalSourceTrace(layout_box_index=-1, layout_box_class="text", stage3_block_ids=["p1-b1"], stage3_table_ids=[])),
        CanonicalElement(element_id="b", type="paragraph", page_number=1, reading_order=1, document_order=1, bbox=[60,140,540,170], text="B", role_source="test", source=CanonicalSourceTrace(layout_box_index=-1, layout_box_class="text", stage3_block_ids=["p1-b2"], stage3_table_ids=[])),
        CanonicalElement(element_id="c", type="paragraph", page_number=1, reading_order=2, document_order=2, bbox=[60,180,540,210], text="C", role_source="test", source=CanonicalSourceTrace(layout_box_index=-1, layout_box_class="text", stage3_block_ids=["p1-b3"], stage3_table_ids=[])),
    ]
    operation = CorrectionOperation(
        operation_id="op-gap-merge", operation="merge", page_number=1,
        source_element_ids=["a", "c"],
        result_elements=[CorrectionElementSpec(element_id="merged", type="paragraph", bbox=[60,100,540,210])],
        created_at=datetime.now(timezone.utc),
    )
    import pytest
    from app.services.corrections import InvalidCorrectionError
    with pytest.raises(InvalidCorrectionError, match="not contiguous"):
        resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))


def test_relabel_clause_removes_stale_clause_record():
    _, extraction, structure = _fixture()
    element = structure.pages[0].elements[1]
    element.type = "clause"; element.clause_id = "clause-test"; element.clause_number = "1.1"
    structure.clauses = [ClauseRecord(clause_id="clause-test", number="1.1", kind="clause", element_id=element.element_id, page_number=1)]
    operation = CorrectionOperation(operation_id="op-clause-to-paragraph", operation="relabel", page_number=1, source_element_ids=[element.element_id], new_type="paragraph", created_at=datetime.now(timezone.utc))
    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))
    assert resolved.structure.clauses == []
    corrected = next(item for item in resolved.structure.pages[0].elements if item.element_id == element.element_id)
    assert corrected.clause_id is None


def test_suppress_prunes_section_content_element_ids():
    _, extraction, structure = _fixture()
    header, body = structure.pages[0].elements[:2]
    header.type = "section_header"; header.section_id = "sec-test"; body.section_id = "sec-test"
    structure.sections = [SectionRecord(section_id="sec-test", title="Header", level=1, page_number=1, element_id=header.element_id, level_source="font_rank", content_element_ids=[body.element_id])]
    operation = CorrectionOperation(operation_id="op-delete-body", operation="delete", page_number=1, source_element_ids=[body.element_id], created_at=datetime.now(timezone.utc))
    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))
    assert resolved.structure.sections[0].content_element_ids == []


def test_move_resize_reconciles_clear_vertical_reading_order():
    _, extraction, structure = _fixture()
    operation = CorrectionOperation(
        operation_id="op-move-above", operation="move_resize", page_number=1,
        source_element_ids=["p1-e2"], result_elements=[CorrectionElementSpec(element_id="p1-e2", type="paragraph", bbox=[60, 5, 540, 25])],
        created_at=datetime.now(timezone.utc),
    )
    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))
    assert resolved.structure.pages[0].elements[0].element_id == "p1-e2"
    assert resolved.structure.pages[0].elements[0].reading_order == 0


def test_small_draw_inside_coarse_span_recovers_text_and_provenance():
    _, extraction, structure = _fixture()
    operation = CorrectionOperation(
        operation_id="op-small-draw", operation="draw", page_number=1,
        result_elements=[CorrectionElementSpec(element_id="small", type="paragraph", bbox=[70, 145, 130, 175])],
        created_at=datetime.now(timezone.utc),
    )
    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))
    item = next(item for item in resolved.structure.pages[0].elements if item.element_id == "small")
    assert item.text == "Body paragraph"
    assert "p1-b2" in item.source.stage3_block_ids


def test_cross_page_definition_membership_rebuilds_one_definition_entry():
    extraction, structure = _cross_page_fixture()
    term = structure.pages[0].elements[1]; target = structure.pages[1].elements[0]
    term.type = "definition_term"; term.definition_entry_id = None
    target.type = "definition_text"; target.definition_entry_id = None
    operation = CorrectionOperation(operation_id="op-cross-def", operation="link_definition", page_number=1, target_page_number=2, source_element_ids=[term.element_id, target.element_id], created_at=datetime.now(timezone.utc))
    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))
    resolved_term = next(item for item in resolved.structure.pages[0].elements if item.element_id == term.element_id)
    resolved_target = next(item for item in resolved.structure.pages[1].elements if item.element_id == target.element_id)
    assert resolved_term.definition_entry_id == resolved_target.definition_entry_id
    assert len(resolved.structure.definitions) == 1
    assert resolved.structure.definitions[0].start_page == 1
    assert resolved.structure.definitions[0].end_page == 2
    assert resolved.structure.definitions[0].spans_multiple_pages is True


def test_non_finite_bbox_is_rejected():
    _, extraction, structure = _fixture()
    operation = CorrectionOperation(
        operation_id="op-nan", operation="move_resize", page_number=1,
        source_element_ids=["p1-e2"], result_elements=[CorrectionElementSpec(element_id="p1-e2", type="paragraph", bbox=[60, 140, float("nan"), 180])],
        created_at=datetime.now(timezone.utc),
    )
    import pytest
    from app.services.corrections import InvalidCorrectionError
    with pytest.raises(InvalidCorrectionError, match="finite"):
        resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))


def test_relabel_table_removes_stale_logical_table_record():
    _, extraction, structure = _fixture()
    element = structure.pages[0].elements[1]
    element.type = "table"
    element.logical_table_id = "table-test"
    element.table = CanonicalTable(row_count=1, col_count=2, cells=[["A", "B"]], markdown="|A|B|")
    structure.tables = [LogicalTable(
        logical_table_id="table-test",
        fragment_element_ids=[element.element_id],
        start_page=1,
        end_page=1,
        spans_multiple_pages=False,
        row_count=1,
        col_count=2,
        cells=[["A", "B"]],
    )]
    operation = CorrectionOperation(
        operation_id="op-table-to-paragraph", operation="relabel", page_number=1,
        source_element_ids=[element.element_id], new_type="paragraph", created_at=datetime.now(timezone.utc),
    )
    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))
    corrected = next(item for item in resolved.structure.pages[0].elements if item.element_id == element.element_id)
    assert corrected.type == "paragraph"
    assert corrected.table is None
    assert corrected.logical_table_id is None
    assert resolved.structure.tables == []


def test_generic_split_rejects_table_elements():
    _, extraction, structure = _fixture()
    element = structure.pages[0].elements[1]
    element.type = "table"
    element.table = CanonicalTable(row_count=1, col_count=1, cells=[["Body paragraph"]])
    operation = CorrectionOperation(
        operation_id="op-table-split", operation="split", page_number=1,
        source_element_ids=[element.element_id],
        result_elements=[
            CorrectionElementSpec(element_id="table-a", type="table", bbox=[60, 140, 540, 160]),
            CorrectionElementSpec(element_id="table-b", type="table", bbox=[60, 160, 540, 180]),
        ], created_at=datetime.now(timezone.utc),
    )
    import pytest
    from app.services.corrections import InvalidCorrectionError
    with pytest.raises(InvalidCorrectionError, match="Split is not supported for table"):
        resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))


def test_generic_draw_rejects_table_without_cell_data():
    _, extraction, structure = _fixture()
    operation = CorrectionOperation(
        operation_id="op-draw-table", operation="draw", page_number=1,
        result_elements=[CorrectionElementSpec(element_id="new-table", type="table", bbox=[60, 200, 540, 260])],
        created_at=datetime.now(timezone.utc),
    )
    import pytest
    from app.services.corrections import InvalidCorrectionError
    with pytest.raises(InvalidCorrectionError, match="dedicated structural editor"):
        resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))


def test_cross_page_definition_target_page_metadata_is_verified():
    extraction, structure = _cross_page_fixture()
    term = structure.pages[0].elements[1]
    target = structure.pages[1].elements[0]
    term.type = "definition_term"
    target.type = "definition_text"
    operation = CorrectionOperation(
        operation_id="op-cross-def-wrong-page", operation="link_definition", page_number=1, target_page_number=1,
        source_element_ids=[term.element_id, target.element_id], created_at=datetime.now(timezone.utc),
    )
    import pytest
    from app.services.corrections import InvalidCorrectionError
    with pytest.raises(InvalidCorrectionError, match="target_page_number"):
        resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))


def test_geometry_reorder_preserves_untouched_cross_column_relative_order():
    _, extraction, structure = _fixture()
    extraction = extraction.model_copy(deep=True)
    structure = structure.model_copy(deep=True)
    extraction.pages[0].blocks = [
        _text_block("left-top-b", 1, [60, 100, 250, 130], "Left top"),
        _text_block("left-low-b", 2, [60, 200, 250, 230], "Left lower"),
        _text_block("right-top-b", 3, [330, 100, 540, 130], "Right top"),
    ]
    structure.pages[0].elements = [
        CanonicalElement(element_id="left-top", type="paragraph", page_number=1, reading_order=0, document_order=0, bbox=[60,100,250,130], text="Left top", role_source="test", source=CanonicalSourceTrace(layout_box_index=-1, layout_box_class="text", stage3_block_ids=["left-top-b"], stage3_table_ids=[])),
        CanonicalElement(element_id="left-low", type="paragraph", page_number=1, reading_order=1, document_order=1, bbox=[60,200,250,230], text="Left lower", role_source="test", source=CanonicalSourceTrace(layout_box_index=-1, layout_box_class="text", stage3_block_ids=["left-low-b"], stage3_table_ids=[])),
        CanonicalElement(element_id="right-top", type="paragraph", page_number=1, reading_order=2, document_order=2, bbox=[330,100,540,130], text="Right top", role_source="test", source=CanonicalSourceTrace(layout_box_index=-1, layout_box_class="text", stage3_block_ids=["right-top-b"], stage3_table_ids=[])),
    ]
    operation = CorrectionOperation(
        operation_id="op-left-low-adjust", operation="move_resize", page_number=1,
        source_element_ids=["left-low"],
        result_elements=[CorrectionElementSpec(element_id="left-low", type="paragraph", bbox=[60, 210, 250, 240])],
        created_at=datetime.now(timezone.utc),
    )
    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))
    assert [item.element_id for item in resolved.structure.pages[0].elements] == ["left-top", "left-low", "right-top"]


def test_generic_relabel_rejects_promotion_to_record_bearing_structural_type():
    _, extraction, structure = _fixture()
    operation = CorrectionOperation(
        operation_id="op-promote-section", operation="relabel", page_number=1,
        source_element_ids=["p1-e2"], new_type="section_header", created_at=datetime.now(timezone.utc),
    )
    import pytest
    from app.services.corrections import InvalidCorrectionError
    with pytest.raises(InvalidCorrectionError, match="dedicated structural editor"):
        resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))


def test_generic_draw_rejects_record_bearing_structural_type():
    _, extraction, structure = _fixture()
    operation = CorrectionOperation(
        operation_id="op-draw-section", operation="draw", page_number=1,
        result_elements=[CorrectionElementSpec(element_id="new-section", type="section_header", bbox=[60, 200, 540, 240])],
        created_at=datetime.now(timezone.utc),
    )
    import pytest
    from app.services.corrections import InvalidCorrectionError
    with pytest.raises(InvalidCorrectionError, match="dedicated structural editor"):
        resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))


def test_relabel_appendix_label_removes_stale_appendix_record_and_membership():
    _, extraction, structure = _fixture()
    label, body = structure.pages[0].elements[:2]
    label.type = "section_header"
    label.appendix_id = "appendix-a"
    body.appendix_id = "appendix-a"
    structure.appendices = [AppendixRecord(
        appendix_id="appendix-a", label="APPENDIX A", label_element_id=label.element_id,
        start_page=1, end_page=1,
    )]
    operation = CorrectionOperation(
        operation_id="op-appendix-to-paragraph", operation="relabel", page_number=1,
        source_element_ids=[label.element_id], new_type="paragraph", created_at=datetime.now(timezone.utc),
    )
    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))
    assert resolved.structure.appendices == []
    assert all(element.appendix_id is None for element in resolved.structure.pages[0].elements)


def test_relabel_metadata_and_title_prunes_document_level_element_references():
    _, extraction, structure = _fixture()
    first, second = structure.pages[0].elements[:2]
    first.type = "title"
    second.type = "document_metadata"
    structure.outline_root_element_id = first.element_id
    structure.metadata_element_ids = [second.element_id]
    operations = [
        CorrectionOperation(
            operation_id="op-title-away", operation="relabel", page_number=1,
            source_element_ids=[first.element_id], new_type="paragraph", created_at=datetime.now(timezone.utc),
        ),
        CorrectionOperation(
            operation_id="op-meta-away", operation="relabel", page_number=1,
            source_element_ids=[second.element_id], new_type="paragraph", created_at=datetime.now(timezone.utc),
        ),
    ]
    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, operations))
    assert resolved.structure.outline_root_element_id is None
    assert resolved.structure.metadata_element_ids == []


def test_span_rebuild_replaces_element_from_exact_legacy_span_ids():
    """Legacy Stage-3 1.0-style fixtures have no persisted span_id fields.

    The resolver must synthesize deterministic IDs and still allow exact
    span-based reconstruction without re-running Stage 3.
    """
    _, extraction, structure = _fixture()
    source = next(item for item in structure.pages[0].elements if item.element_id == "p1-e2")
    assert extraction.pages[0].blocks[1].lines[0].spans[0].span_id is None

    operation = CorrectionOperation(
        operation_id="op-span-rebuild",
        operation="span_rebuild",
        page_number=1,
        source_element_ids=[source.element_id],
        result_elements=[CorrectionElementSpec(
            element_id=source.element_id,
            type="paragraph",
            bbox=[60, 140, 540, 180],
            source_span_ids=["p1-b2-l1-s1"],
        )],
        created_at=datetime.now(timezone.utc),
    )
    artifact = CorrectionArtifact(
        document_id=structure.document_id,
        source_sha256=structure.source_sha256,
        base_structure_schema_version=structure.schema_version,
        base_structured_at=structure.structured_at,
        operations=[operation],
        updated_at=datetime.now(timezone.utc),
    )
    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=artifact)
    item = next(item for item in resolved.structure.pages[0].elements if item.element_id == source.element_id)
    assert item.text == "Body paragraph"
    assert item.bbox == [60.0, 140.0, 540.0, 180.0]
    assert item.source.stage3_block_ids == ["p1-b2"]
    assert item.source.stage3_line_ids == ["p1-b2-l1"]
    assert item.source.stage3_span_ids == ["p1-b2-l1-s1"]
    assert item.role_source == "manual_span_rebuild"


def test_span_rebuild_requires_replacing_overlapping_canonical_element():
    _, extraction, structure = _fixture()
    operation = CorrectionOperation(
        operation_id="op-span-duplicate",
        operation="span_rebuild",
        page_number=1,
        result_elements=[CorrectionElementSpec(
            element_id="manual-span-element",
            type="paragraph",
            bbox=[60, 140, 540, 180],
            source_span_ids=["p1-b2-l1-s1"],
        )],
        created_at=datetime.now(timezone.utc),
    )
    artifact = CorrectionArtifact(
        document_id=structure.document_id,
        source_sha256=structure.source_sha256,
        base_structure_schema_version=structure.schema_version,
        base_structured_at=structure.structured_at,
        operations=[operation],
        updated_at=datetime.now(timezone.utc),
    )
    import pytest
    with pytest.raises(ValueError, match="not being replaced"):
        resolve_structure(automatic=structure, extraction=extraction, corrections=artifact)


def test_span_rebuild_rejects_unknown_or_reused_span_ids():
    _, extraction, structure = _fixture()
    source = next(item for item in structure.pages[0].elements if item.element_id == "p1-e2")
    import pytest

    unknown = CorrectionOperation(
        operation_id="op-span-unknown",
        operation="span_rebuild",
        page_number=1,
        source_element_ids=[source.element_id],
        result_elements=[CorrectionElementSpec(
            element_id=source.element_id,
            type="paragraph",
            bbox=[60, 140, 540, 180],
            source_span_ids=["p1-missing-span"],
        )],
        created_at=datetime.now(timezone.utc),
    )
    artifact = CorrectionArtifact(
        document_id=structure.document_id,
        source_sha256=structure.source_sha256,
        base_structure_schema_version=structure.schema_version,
        base_structured_at=structure.structured_at,
        operations=[unknown],
        updated_at=datetime.now(timezone.utc),
    )
    with pytest.raises(ValueError, match="Unknown Stage 3 span IDs"):
        resolve_structure(automatic=structure, extraction=extraction, corrections=artifact)

    reused = CorrectionOperation(
        operation_id="op-span-reused",
        operation="span_rebuild",
        page_number=1,
        source_element_ids=[source.element_id],
        result_elements=[
            CorrectionElementSpec(element_id="span-a", type="paragraph", bbox=[60, 140, 540, 180], source_span_ids=["p1-b2-l1-s1"]),
            CorrectionElementSpec(element_id="span-b", type="paragraph", bbox=[60, 140, 540, 180], source_span_ids=["p1-b2-l1-s1"]),
        ],
        created_at=datetime.now(timezone.utc),
    )
    artifact.operations = [reused]
    with pytest.raises(ValueError, match="same Stage 3 span"):
        resolve_structure(automatic=structure, extraction=extraction, corrections=artifact)


def test_span_rebuild_rejects_stale_submitted_bbox():
    _, extraction, structure = _fixture()
    source = next(item for item in structure.pages[0].elements if item.element_id == "p1-e2")
    operation = CorrectionOperation(
        operation_id="op-span-stale-bbox",
        operation="span_rebuild",
        page_number=1,
        source_element_ids=[source.element_id],
        result_elements=[CorrectionElementSpec(
            element_id=source.element_id,
            type="paragraph",
            bbox=[70, 150, 500, 170],
            source_span_ids=["p1-b2-l1-s1"],
        )],
        created_at=datetime.now(timezone.utc),
    )
    artifact = CorrectionArtifact(
        document_id=structure.document_id,
        source_sha256=structure.source_sha256,
        base_structure_schema_version=structure.schema_version,
        base_structured_at=structure.structured_at,
        operations=[operation],
        updated_at=datetime.now(timezone.utc),
    )
    import pytest
    with pytest.raises(ValueError, match="changed|does not match"):
        resolve_structure(automatic=structure, extraction=extraction, corrections=artifact)


def _replace_body_with_spans(extraction, structure, parts):
    """Replace the fixture body line with explicit span geometry for span-correction tests."""
    block = extraction.pages[0].blocks[1]
    line = block.lines[0]
    spans = []
    for text, x0, x1 in parts:
        spans.append(TextSpan(text=text, bbox=[x0, 140, x1, 180], font="Test", size=11))
    line.text = "".join(span.text for span in spans)
    line.bbox = [parts[0][1], 140, parts[-1][2], 180]
    line.spans = spans
    block.text = line.text
    block.bbox = list(line.bbox)
    body = next(item for item in structure.pages[0].elements if item.element_id == "p1-e2")
    body.text = line.text
    body.bbox = list(line.bbox)
    body.source.stage3_block_ids = [block.block_id]
    body.source.stage3_line_ids = ["p1-b2-l1"]
    body.source.stage3_span_ids = [f"p1-b2-l1-s{index}" for index in range(1, len(spans) + 1)]
    return body


def test_stage4_source_trace_contains_stable_line_and_span_ids_for_legacy_extraction():
    _, extraction, structure = _fixture()
    assert extraction.pages[0].blocks[1].lines[0].line_id is None
    assert extraction.pages[0].blocks[1].lines[0].spans[0].span_id is None
    body = next(item for item in structure.pages[0].elements if item.element_id == "p1-e2")
    assert body.source.stage3_line_ids == ["p1-b2-l1"]
    assert body.source.stage3_span_ids == ["p1-b2-l1-s1"]


def test_span_rebuild_rejects_partial_source_without_residual_result():
    _, extraction, structure = _fixture()
    body = _replace_body_with_spans(
        extraction,
        structure,
        [("financial group", 60, 200), (" means a group", 200, 540)],
    )
    operation = CorrectionOperation(
        operation_id="op-span-partial-loss",
        operation="span_rebuild",
        page_number=1,
        source_element_ids=[body.element_id],
        result_elements=[CorrectionElementSpec(
            element_id="manual-term",
            type="definition_term",
            bbox=[60, 140, 200, 180],
            source_span_ids=["p1-b2-l1-s1"],
        )],
        created_at=datetime.now(timezone.utc),
    )
    import pytest
    from app.services.corrections import InvalidCorrectionError
    with pytest.raises(InvalidCorrectionError, match="discard unassigned source text"):
        resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))


def test_span_rebuild_preserves_unselected_source_spans_as_residual_element():
    _, extraction, structure = _fixture()
    body = _replace_body_with_spans(
        extraction,
        structure,
        [("financial group", 60, 200), (" means a group", 200, 540)],
    )
    operation = CorrectionOperation(
        operation_id="op-span-repartition",
        operation="span_rebuild",
        page_number=1,
        source_element_ids=[body.element_id],
        result_elements=[
            CorrectionElementSpec(
                element_id="manual-term",
                type="definition_term",
                bbox=[60, 140, 200, 180],
                source_span_ids=["p1-b2-l1-s1"],
            ),
            CorrectionElementSpec(
                element_id=body.element_id,
                type="paragraph",
                bbox=[200, 140, 540, 180],
                source_span_ids=["p1-b2-l1-s2"],
            ),
        ],
        created_at=datetime.now(timezone.utc),
    )
    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))
    page = resolved.structure.pages[0]
    term = next(item for item in page.elements if item.element_id == "manual-term")
    residual = next(item for item in page.elements if item.element_id == body.element_id)
    assert term.type == "definition_term"
    assert term.text == "financial group"
    assert term.source.stage3_span_ids == ["p1-b2-l1-s1"]
    assert residual.type == "paragraph"
    assert residual.text == "means a group"
    assert residual.source.stage3_span_ids == ["p1-b2-l1-s2"]
    assert "financial group" in page.body_text
    assert "means a group" in page.body_text


def test_span_rebuild_can_create_element_from_unrepresented_stage3_span():
    _, extraction, structure = _fixture()
    body = _replace_body_with_spans(
        extraction,
        structure,
        [("missing term", 60, 200), (" other text", 200, 540)],
    )
    structure.pages[0].elements = [item for item in structure.pages[0].elements if item.element_id != body.element_id]
    operation = CorrectionOperation(
        operation_id="op-span-create-missing",
        operation="span_rebuild",
        page_number=1,
        result_elements=[CorrectionElementSpec(
            element_id="manual-missing-term",
            type="definition_term",
            bbox=[60, 140, 200, 180],
            source_span_ids=["p1-b2-l1-s1"],
        )],
        created_at=datetime.now(timezone.utc),
    )
    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))
    created = next(item for item in resolved.structure.pages[0].elements if item.element_id == "manual-missing-term")
    assert created.text == "missing term"
    assert created.source.stage3_span_ids == ["p1-b2-l1-s1"]


def test_span_rebuild_rejects_noncontiguous_span_group_even_when_residual_is_preserved():
    _, extraction, structure = _fixture()
    body = _replace_body_with_spans(
        extraction,
        structure,
        [("A", 60, 150), ("B", 150, 300), ("C", 300, 540)],
    )
    operation = CorrectionOperation(
        operation_id="op-span-noncontiguous",
        operation="span_rebuild",
        page_number=1,
        source_element_ids=[body.element_id],
        result_elements=[
            CorrectionElementSpec(
                element_id="manual-ac",
                type="paragraph",
                bbox=[60, 140, 540, 180],
                source_span_ids=["p1-b2-l1-s1", "p1-b2-l1-s3"],
            ),
            CorrectionElementSpec(
                element_id=body.element_id,
                type="paragraph",
                bbox=[150, 140, 300, 180],
                source_span_ids=["p1-b2-l1-s2"],
            ),
        ],
        created_at=datetime.now(timezone.utc),
    )
    import pytest
    from app.services.corrections import InvalidCorrectionError
    with pytest.raises(InvalidCorrectionError, match="skips text inside its derived bbox"):
        resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))


def test_span_rebuild_rejects_record_bearing_result_type():
    _, extraction, structure = _fixture()
    body = next(item for item in structure.pages[0].elements if item.element_id == "p1-e2")
    operation = CorrectionOperation(
        operation_id="op-span-table",
        operation="span_rebuild",
        page_number=1,
        source_element_ids=[body.element_id],
        result_elements=[CorrectionElementSpec(
            element_id=body.element_id,
            type="table",
            bbox=[60, 140, 540, 180],
            source_span_ids=["p1-b2-l1-s1"],
        )],
        created_at=datetime.now(timezone.utc),
    )
    import pytest
    from app.services.corrections import InvalidCorrectionError
    with pytest.raises(InvalidCorrectionError, match="record-bearing structural"):
        resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))


def test_span_rebuild_middle_selection_can_preserve_two_residual_groups_losslessly():
    _, extraction, structure = _fixture()
    body = _replace_body_with_spans(
        extraction,
        structure,
        [("A", 60, 150), ("B", 150, 300), ("C", 300, 540)],
    )
    operation = CorrectionOperation(
        operation_id="op-span-middle",
        operation="span_rebuild",
        page_number=1,
        source_element_ids=[body.element_id],
        result_elements=[
            CorrectionElementSpec(
                element_id="manual-b",
                type="definition_term",
                bbox=[150, 140, 300, 180],
                source_span_ids=["p1-b2-l1-s2"],
            ),
            CorrectionElementSpec(
                element_id=body.element_id,
                type="paragraph",
                bbox=[60, 140, 150, 180],
                source_span_ids=["p1-b2-l1-s1"],
            ),
            CorrectionElementSpec(
                element_id="manual-c-residual",
                type="paragraph",
                bbox=[300, 140, 540, 180],
                source_span_ids=["p1-b2-l1-s3"],
            ),
        ],
        created_at=datetime.now(timezone.utc),
    )
    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))
    page = resolved.structure.pages[0]
    by_id = {item.element_id: item for item in page.elements}
    assert by_id[body.element_id].text == "A"
    assert by_id["manual-b"].text == "B"
    assert by_id["manual-c-residual"].text == "C"
    body_lines = page.body_text.splitlines()
    assert body_lines.count("A") == 1
    assert body_lines.count("B") == 1
    assert body_lines.count("C") == 1


def _structural_fixture():
    _, extraction, structure = _fixture()
    header = structure.pages[0].elements[0]
    body = structure.pages[0].elements[1]

    header.type = "section_header"
    header.section_id = "sec-1"
    header.heading_level = 1
    header.heading_level_source = "font_rank"
    body.type = "clause"
    body.section_id = "sec-1"
    body.clause_id = "clause-1"
    body.clause_number = "1.1"
    body.parent_clause_id = None

    structure.sections = [SectionRecord(
        section_id="sec-1",
        title=header.text,
        level=1,
        page_number=1,
        element_id=header.element_id,
        level_source="font_rank",
        content_element_ids=[body.element_id],
    )]
    structure.clauses = [ClauseRecord(
        clause_id="clause-1",
        number="1.1",
        kind="clause",
        element_id=body.element_id,
        page_number=1,
        section_id="sec-1",
    )]
    structure.relationships = [StructuralRelation(
        relation_id="rel-base-clause-section",
        type="belongs_to",
        source_element_id=body.element_id,
        target_element_id=header.element_id,
        evidence="clause inherits active section",
    )]
    structure.summary.section_count = 1
    structure.summary.clause_count = 1
    structure.summary.relation_count = 1
    return extraction, structure


def test_structured_subclause_correction_creates_record_and_parent_relation():
    extraction, structure = _structural_fixture()
    manual = CanonicalElement(
        element_id="manual-d",
        type="paragraph",
        page_number=1,
        reading_order=2,
        document_order=2,
        bbox=[60, 200, 540, 240],
        text="(d) joint ownership",
        role_source="manual_draw_preview",
        source=CanonicalSourceTrace(
            layout_box_index=-1,
            layout_box_class="manual_draw_preview",
            stage3_block_ids=[],
            stage3_table_ids=[],
        ),
    )
    structure.pages[0].elements.append(manual)
    structure.summary.element_count += 1

    operation = CorrectionOperation(
        operation_id="op-structured-subclause",
        operation="set_structure",
        page_number=1,
        source_element_ids=[manual.element_id],
        structure=CorrectionStructureSpec(
            element_id=manual.element_id,
            type="subclause",
            section_id="sec-1",
            clause_id="clause-2",
            parent_clause_id="clause-1",
            subclause_marker="(d)",
        ),
        created_at=datetime.now(timezone.utc),
    )
    resolved = resolve_structure(
        automatic=structure,
        extraction=extraction,
        corrections=_artifact_for(structure, [operation]),
    )
    corrected = next(item for item in resolved.structure.pages[0].elements if item.element_id == "manual-d")
    assert corrected.type == "subclause"
    assert corrected.section_id == "sec-1"
    assert corrected.clause_id == "clause-2"
    assert corrected.parent_clause_id == "clause-1"
    assert corrected.subclause_marker == "(d)"
    record = next(item for item in resolved.structure.clauses if item.clause_id == "clause-2")
    assert record.kind == "subclause"
    assert record.parent_clause_id == "clause-1"
    assert "manual-d" in resolved.structure.sections[0].content_element_ids
    assert any(
        relation.type == "parent_of"
        and relation.source_element_id == "p1-e2"
        and relation.target_element_id == "manual-d"
        for relation in resolved.structure.relationships
    )
    assert resolved.integrity.status == "pass"


def test_structured_subclause_rejects_missing_parent_clause():
    extraction, structure = _structural_fixture()
    manual = structure.pages[0].elements[1].model_copy(deep=True)
    manual.element_id = "manual-d"
    manual.type = "paragraph"
    manual.clause_id = None
    manual.clause_number = None
    manual.parent_clause_id = None
    manual.section_id = None
    structure.pages[0].elements.append(manual)

    operation = CorrectionOperation(
        operation_id="op-bad-parent",
        operation="set_structure",
        page_number=1,
        source_element_ids=[manual.element_id],
        structure=CorrectionStructureSpec(
            element_id=manual.element_id,
            type="subclause",
            section_id="sec-1",
            clause_id="clause-2",
            parent_clause_id="clause-missing",
            subclause_marker="(d)",
        ),
        created_at=datetime.now(timezone.utc),
    )
    import pytest
    from app.services.corrections import InvalidCorrectionError
    with pytest.raises(InvalidCorrectionError, match="missing parent clause"):
        resolve_structure(
            automatic=structure,
            extraction=extraction,
            corrections=_artifact_for(structure, [operation]),
        )


def test_structured_section_id_rename_migrates_memberships():
    extraction, structure = _structural_fixture()
    header = structure.pages[0].elements[0]
    operation = CorrectionOperation(
        operation_id="op-rename-section",
        operation="set_structure",
        page_number=1,
        source_element_ids=[header.element_id],
        structure=CorrectionStructureSpec(
            element_id=header.element_id,
            type="section_header",
            section_id="sec-renamed",
            heading_level=1,
        ),
        created_at=datetime.now(timezone.utc),
    )
    resolved = resolve_structure(
        automatic=structure,
        extraction=extraction,
        corrections=_artifact_for(structure, [operation]),
    )
    assert resolved.structure.sections[0].section_id == "sec-renamed"
    assert resolved.structure.pages[0].elements[0].section_id == "sec-renamed"
    assert resolved.structure.pages[0].elements[1].section_id == "sec-renamed"
    assert resolved.structure.clauses[0].section_id == "sec-renamed"
    assert resolved.structure.sections[0].content_element_ids == ["p1-e2"]
    assert resolved.integrity.status == "pass"


def test_structural_section_cycle_is_rejected():
    extraction, structure = _structural_fixture()
    second = CanonicalElement(
        element_id="section-two",
        type="section_header",
        page_number=1,
        reading_order=2,
        document_order=2,
        bbox=[60, 200, 540, 230],
        text="Second",
        section_id="sec-2",
        heading_level=2,
        heading_level_source="font_rank",
        role_source="fixture",
        source=CanonicalSourceTrace(layout_box_index=-1, layout_box_class="section-header", stage3_block_ids=[], stage3_table_ids=[]),
    )
    structure.pages[0].elements.append(second)
    structure.sections.append(SectionRecord(
        section_id="sec-2", title="Second", level=2, page_number=1,
        element_id=second.element_id, parent_section_id="sec-1", level_source="font_rank",
    ))
    operation = CorrectionOperation(
        operation_id="op-cycle-section",
        operation="set_structure",
        page_number=1,
        source_element_ids=[structure.pages[0].elements[0].element_id],
        structure=CorrectionStructureSpec(
            element_id=structure.pages[0].elements[0].element_id,
            type="section_header",
            section_id="sec-1",
            parent_section_id="sec-2",
            heading_level=1,
        ),
        created_at=datetime.now(timezone.utc),
    )
    import pytest
    from app.services.corrections import InvalidCorrectionError
    with pytest.raises(InvalidCorrectionError, match="Section hierarchy cycle"):
        resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))


def test_manual_parent_of_relation_is_rejected_in_favor_of_structural_editor():
    extraction, structure = _structural_fixture()
    operation = CorrectionOperation(
        operation_id="op-direct-parent",
        operation="add_relationship",
        page_number=1,
        relationships=[CorrectionRelationshipSpec(
            relation_id="manual-parent",
            type="parent_of",
            source_element_id="p1-e2",
            target_element_id="p1-e1",
            source_page_number=1,
            target_page_number=1,
        )],
        created_at=datetime.now(timezone.utc),
    )
    import pytest
    from app.services.corrections import InvalidCorrectionError
    with pytest.raises(InvalidCorrectionError, match="dedicated structural editor"):
        resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [operation]))


def test_integrity_report_detects_duplicate_relationship_edge():
    extraction, structure = _structural_fixture()
    structure.relationships.append(StructuralRelation(
        relation_id="rel-duplicate",
        type="belongs_to",
        source_element_id="p1-e2",
        target_element_id="p1-e1",
        evidence="duplicate fixture edge",
    ))
    resolved = resolve_structure(
        automatic=structure,
        extraction=extraction,
        corrections=_artifact_for(structure, []),
    )
    assert resolved.integrity.status == "pass"
    # Derived clause→section relations are normalized to one canonical edge.
    assert len([
        relation for relation in resolved.structure.relationships
        if relation.type == "belongs_to" and relation.source_element_id == "p1-e2" and relation.target_element_id == "p1-e1"
    ]) == 1


def test_integrity_report_is_present_for_uncorrected_valid_structure():
    _, extraction, structure = _fixture()
    resolved = resolve_structure(
        automatic=structure,
        extraction=extraction,
        corrections=_artifact_for(structure, []),
    )
    assert resolved.integrity.status == "pass"
    assert resolved.integrity.counts["elements"] == resolved.structure.summary.element_count



def test_manual_relabel_removes_stale_figure_caption_membership_and_relation():
    _, extraction, structure = _fixture()
    caption = structure.pages[0].elements[0]
    caption.type = "caption"
    caption.heading_level = None
    caption.heading_level_source = None
    figure = CanonicalElement(
        element_id="p1-figure",
        type="figure",
        page_number=1,
        reading_order=2,
        document_order=2,
        bbox=[100, 210, 500, 420],
        text="",
        figure_id="figure-1",
        role_source="fixture",
        source=CanonicalSourceTrace(
            layout_box_index=-1,
            layout_box_class="figure",
            stage3_block_ids=[],
            stage3_table_ids=[],
        ),
    )
    structure.pages[0].elements.append(figure)
    structure.figures = [FigureRecord(
        figure_id="figure-1",
        element_id=figure.element_id,
        page_number=1,
        caption_element_ids=[caption.element_id],
    )]
    structure.relationships = [StructuralRelation(
        relation_id="rel-caption",
        type="caption_of",
        source_element_id=caption.element_id,
        target_element_id=figure.element_id,
        evidence="caption/illustration label immediately precedes figure",
    )]

    operation = CorrectionOperation(
        operation_id="op-caption-to-paragraph",
        operation="relabel",
        page_number=1,
        source_element_ids=[caption.element_id],
        new_type="paragraph",
        created_at=datetime.now(timezone.utc),
    )
    resolved = resolve_structure(
        automatic=structure,
        extraction=extraction,
        corrections=_artifact_for(structure, [operation]),
    )
    assert resolved.structure.figures[0].caption_element_ids == []
    assert not any(relation.type == "caption_of" for relation in resolved.structure.relationships)
    assert resolved.integrity.status == "pass"


def test_appendix_relation_is_removed_when_title_is_relabelled_away():
    _, extraction, structure = _fixture()
    label, title = structure.pages[0].elements
    label.type = "section_header"
    label.text = "APPENDIX A"
    label.appendix_id = "appendix-1"
    label.heading_level = 1
    label.heading_level_source = "font_rank"
    title.type = "subtitle"
    title.appendix_id = "appendix-1"
    structure.appendices = [AppendixRecord(
        appendix_id="appendix-1",
        label="APPENDIX A",
        label_element_id=label.element_id,
        title=title.text,
        title_element_id=title.element_id,
        start_page=1,
        end_page=1,
    )]
    structure.relationships = [StructuralRelation(
        relation_id="rel-appendix-title",
        type="belongs_to",
        source_element_id=title.element_id,
        target_element_id=label.element_id,
        evidence="appendix title immediately follows appendix label",
    )]

    operation = CorrectionOperation(
        operation_id="op-title-to-paragraph",
        operation="relabel",
        page_number=1,
        source_element_ids=[title.element_id],
        new_type="paragraph",
        created_at=datetime.now(timezone.utc),
    )
    resolved = resolve_structure(
        automatic=structure,
        extraction=extraction,
        corrections=_artifact_for(structure, [operation]),
    )
    assert resolved.structure.appendices == []
    assert title.element_id not in [relation.source_element_id for relation in resolved.structure.relationships if relation.type == "belongs_to"]
    corrected_title = next(element for element in resolved.structure.pages[0].elements if element.element_id == title.element_id)
    assert corrected_title.appendix_id is None
    assert resolved.integrity.status == "pass"


def test_relabelled_table_fragment_removes_logical_table_and_stale_continuation():
    _, extraction, structure = _fixture()
    first = structure.pages[0].elements[1]
    first.type = "table"
    first.table = CanonicalTable(row_count=1, col_count=3, cells=[["1", "A", "5"]])
    first.logical_table_id = "table-1"
    second = CanonicalElement(
        element_id="p2-e1",
        type="table",
        page_number=2,
        reading_order=0,
        document_order=2,
        bbox=[60, 30, 540, 120],
        text="2\tB\t6",
        logical_table_id="table-1",
        table=CanonicalTable(row_count=1, col_count=3, cells=[["2", "B", "6"]]),
        role_source="fixture",
        source=CanonicalSourceTrace(
            layout_box_index=0,
            layout_box_class="table",
            stage3_block_ids=[],
            stage3_table_ids=[],
        ),
    )
    structure.pages.append(StructuredPage(
        page_number=2,
        width=600,
        height=800,
        elements=[second],
        body_text=second.text,
    ))
    structure.tables = [LogicalTable(
        logical_table_id="table-1",
        fragment_element_ids=[first.element_id, second.element_id],
        start_page=1,
        end_page=2,
        spans_multiple_pages=True,
        row_count=2,
        col_count=3,
        cells=[["1", "A", "5"], ["2", "B", "6"]],
        merge_source="cross_page_geometry",
    )]
    structure.relationships = [StructuralRelation(
        relation_id="rel-table-1",
        type="continues",
        source_element_id=first.element_id,
        target_element_id=second.element_id,
        evidence="adjacent-page tables share column count, x-boundaries, semantic context, and page-edge geometry",
    )]

    operation = CorrectionOperation(
        operation_id="op-table-to-paragraph",
        operation="relabel",
        page_number=1,
        source_element_ids=[first.element_id],
        new_type="paragraph",
        created_at=datetime.now(timezone.utc),
    )
    resolved = resolve_structure(
        automatic=structure,
        extraction=extraction,
        corrections=_artifact_for(structure, [operation]),
    )
    assert resolved.structure.tables == []
    assert not any(relation.relation_id == "rel-table-1" for relation in resolved.structure.relationships)
    corrected_second = next(element for page in resolved.structure.pages for element in page.elements if element.element_id == second.element_id)
    assert corrected_second.logical_table_id is None
    assert resolved.integrity.status == "pass"


def test_manual_table_continuation_between_different_logical_tables_fails_integrity():
    _, extraction, structure = _fixture()
    first = structure.pages[0].elements[1]
    first.type = "table"
    first.table = CanonicalTable(row_count=1, col_count=3, cells=[["1", "A", "5"]])
    first.logical_table_id = "table-1"
    second = CanonicalElement(
        element_id="p2-e1",
        type="table",
        page_number=2,
        reading_order=0,
        document_order=2,
        bbox=[60, 30, 540, 120],
        text="2\tB\t6",
        logical_table_id="table-2",
        table=CanonicalTable(row_count=1, col_count=3, cells=[["2", "B", "6"]]),
        role_source="fixture",
        source=CanonicalSourceTrace(layout_box_index=0, layout_box_class="table", stage3_block_ids=[], stage3_table_ids=[]),
    )
    structure.pages.append(StructuredPage(page_number=2, width=600, height=800, elements=[second], body_text=second.text))
    structure.tables = [
        LogicalTable(logical_table_id="table-1", fragment_element_ids=[first.element_id], start_page=1, end_page=1, spans_multiple_pages=False, row_count=1, col_count=3, cells=[["1", "A", "5"]]),
        LogicalTable(logical_table_id="table-2", fragment_element_ids=[second.element_id], start_page=2, end_page=2, spans_multiple_pages=False, row_count=1, col_count=3, cells=[["2", "B", "6"]]),
    ]
    structure.relationships = []
    operation = CorrectionOperation(
        operation_id="op-bad-table-continues",
        operation="add_relationship",
        page_number=1,
        relationships=[CorrectionRelationshipSpec(
            relation_id="manual-bad-table-continues",
            type="continues",
            source_element_id=first.element_id,
            target_element_id=second.element_id,
            source_page_number=1,
            target_page_number=2,
        )],
        created_at=datetime.now(timezone.utc),
    )
    resolved = resolve_structure(
        automatic=structure,
        extraction=extraction,
        corrections=_artifact_for(structure, [operation]),
    )
    assert resolved.integrity.status == "fail"
    assert any(issue.code == "continues_table_mismatch" for issue in resolved.integrity.errors)


def test_cross_page_logical_table_rebuilds_missing_continuation_relation():
    _, extraction, structure = _fixture()
    first = structure.pages[0].elements[1]
    first.type = "table"
    first.table = CanonicalTable(row_count=1, col_count=3, cells=[["1", "A", "5"]])
    first.logical_table_id = "table-1"
    second = CanonicalElement(
        element_id="p2-e1",
        type="table",
        page_number=2,
        reading_order=0,
        document_order=2,
        bbox=[60, 30, 540, 120],
        text="2\tB\t6",
        logical_table_id="table-1",
        table=CanonicalTable(row_count=1, col_count=3, cells=[["2", "B", "6"]]),
        role_source="fixture",
        source=CanonicalSourceTrace(layout_box_index=0, layout_box_class="table", stage3_block_ids=[], stage3_table_ids=[]),
    )
    structure.pages.append(StructuredPage(page_number=2, width=600, height=800, elements=[second], body_text=second.text))
    structure.tables = [LogicalTable(
        logical_table_id="table-1",
        fragment_element_ids=[first.element_id, second.element_id],
        start_page=1,
        end_page=2,
        spans_multiple_pages=True,
        row_count=2,
        col_count=3,
        cells=[["1", "A", "5"], ["2", "B", "6"]],
        merge_source="cross_page_geometry",
    )]
    structure.relationships = []

    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, []))
    assert any(
        relation.type == "continues"
        and relation.source_element_id == first.element_id
        and relation.target_element_id == second.element_id
        for relation in resolved.structure.relationships
    )
    assert resolved.integrity.status == "pass"


def test_cross_page_definition_membership_rebuilds_continuation_relation():
    _, extraction, structure = _fixture()
    term, first_text = structure.pages[0].elements
    term.type = "definition_term"
    term.heading_level = None
    term.heading_level_source = None
    term.definition_entry_id = "def-cross"
    first_text.type = "definition_text"
    first_text.definition_entry_id = "def-cross"
    continuation = CanonicalElement(
        element_id="p2-e1",
        type="definition_text",
        page_number=2,
        reading_order=0,
        document_order=2,
        bbox=[300, 30, 540, 120],
        text="continued definition text",
        definition_entry_id="def-cross",
        role_source="fixture",
        source=CanonicalSourceTrace(layout_box_index=0, layout_box_class="text", stage3_block_ids=[], stage3_table_ids=[]),
    )
    structure.pages.append(StructuredPage(page_number=2, width=600, height=800, elements=[continuation], body_text=continuation.text))
    structure.definitions = []
    structure.relationships = []

    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, []))
    assert len(resolved.structure.definitions) == 1
    entry = resolved.structure.definitions[0]
    assert entry.definition_id == "def-cross"
    assert entry.definition_element_ids == [first_text.element_id, continuation.element_id]
    assert any(
        relation.type == "continues"
        and relation.source_element_id == first_text.element_id
        and relation.target_element_id == continuation.element_id
        for relation in resolved.structure.relationships
    )
    assert resolved.integrity.status == "pass"

# Stage 4.5.8.12 — relationship semantic validation / approval gate

def test_relation_validation_rejects_parent_section_after_child():
    from app.services.corrections import _relationship_integrity_report
    extraction, structure = _structural_fixture()
    parent = structure.pages[0].elements[0]
    child = CanonicalElement(
        element_id="late-parent-child",
        type="section_header",
        page_number=1,
        reading_order=1,
        document_order=1,
        bbox=[60, 120, 540, 135],
        text="Child section",
        section_id="sec-child",
        heading_level=2,
        heading_level_source="font_rank",
        role_source="fixture",
        source=CanonicalSourceTrace(layout_box_index=-1, layout_box_class="section-header", stage3_block_ids=[], stage3_table_ids=[]),
    )
    structure.pages[0].elements.insert(1, child)
    # Make the current first header occur after the child while remaining the parent.
    parent.document_order = 2
    child.document_order = 1
    structure.sections.append(SectionRecord(
        section_id="sec-child", title="Child section", level=2, page_number=1,
        element_id=child.element_id, parent_section_id="sec-1", level_source="font_rank",
    ))
    report = _relationship_integrity_report(structure)
    assert report.status == "fail"
    assert any(issue.code == "section_parent_not_before_child" for issue in report.errors)


def test_relation_validation_rejects_duplicate_subclause_marker():
    from app.services.corrections import _relationship_integrity_report
    extraction, structure = _structural_fixture()
    parent = structure.clauses[0]
    for index, element_id in enumerate(("sub-a", "sub-b"), start=2):
        element = CanonicalElement(
            element_id=element_id, type="subclause", page_number=1,
            reading_order=index, document_order=index, bbox=[60, 180 + index * 20, 540, 195 + index * 20],
            text="(d) item", section_id="sec-1", clause_id=f"clause-{index}",
            parent_clause_id=parent.clause_id, subclause_marker="(d)", role_source="fixture",
            source=CanonicalSourceTrace(layout_box_index=-1, layout_box_class="list-item", stage3_block_ids=[], stage3_table_ids=[]),
        )
        structure.pages[0].elements.append(element)
        structure.sections[0].content_element_ids.append(element_id)
        structure.clauses.append(ClauseRecord(
            clause_id=f"clause-{index}", number="(d)", kind="subclause", element_id=element_id,
            page_number=1, section_id="sec-1", parent_clause_id=parent.clause_id,
        ))
        structure.relationships.append(StructuralRelation(
            relation_id=f"rel-parent-{index}", type="parent_of", source_element_id=parent.element_id,
            target_element_id=element_id, evidence="fixture", provenance="derived",
        ))
    report = _relationship_integrity_report(structure)
    assert report.status == "fail"
    assert any(issue.code == "duplicate_subclause_marker" for issue in report.errors)


def test_relation_validation_marks_subclause_gap_for_review():
    from app.services.corrections import _relationship_integrity_report
    _, structure = _structural_fixture()
    parent = structure.clauses[0]
    for marker, suffix, order in (("(a)", "a", 2), ("(c)", "c", 3)):
        element = CanonicalElement(
            element_id=f"sub-{suffix}", type="subclause", page_number=1,
            reading_order=order, document_order=order, bbox=[60, 180 + order * 20, 540, 195 + order * 20],
            text=f"{marker} item", section_id="sec-1", clause_id=f"clause-{suffix}",
            parent_clause_id=parent.clause_id, subclause_marker=marker, role_source="fixture",
            source=CanonicalSourceTrace(layout_box_index=-1, layout_box_class="list-item", stage3_block_ids=[], stage3_table_ids=[]),
        )
        structure.pages[0].elements.append(element)
        structure.sections[0].content_element_ids.append(element.element_id)
        structure.clauses.append(ClauseRecord(
            clause_id=f"clause-{suffix}", number=marker, kind="subclause", element_id=element.element_id,
            page_number=1, section_id="sec-1", parent_clause_id=parent.clause_id,
        ))
        structure.relationships.append(StructuralRelation(
            relation_id=f"rel-parent-{suffix}", type="parent_of", source_element_id=parent.element_id,
            target_element_id=element.element_id, evidence="fixture", provenance="derived",
        ))
    report = _relationship_integrity_report(structure)
    assert report.status == "pass"
    assert report.semantic_status == "review_required"
    issue = next(issue for issue in report.warnings if issue.code == "subclause_sibling_gap")
    assert issue.requires_review is True
    assert issue.issue_id.startswith("ri-")


def test_definition_page_metadata_mismatch_is_an_integrity_error():
    from app.services.corrections import _relationship_integrity_report
    _, extraction, structure = _fixture()
    term, text = structure.pages[0].elements[:2]
    term.type = "definition_term"
    text.type = "definition_text"
    term.definition_entry_id = text.definition_entry_id = "def-test"
    from app.schemas import DefinitionEntry
    structure.definitions = [DefinitionEntry(
        definition_id="def-test", term=term.text, term_element_id=term.element_id,
        definition_element_ids=[text.element_id], definition_text=text.text,
        start_page=1, end_page=2, spans_multiple_pages=True, continues_to_next_page=False,
    )]
    report = _relationship_integrity_report(structure)
    assert report.status == "fail"
    assert any(issue.code == "definition_page_range_mismatch" for issue in report.errors)
    assert any(issue.code == "definition_span_flag_mismatch" for issue in report.errors)


def test_logical_table_metadata_mismatch_is_an_integrity_error():
    from app.services.corrections import _relationship_integrity_report
    _, extraction, structure = _fixture()
    element = structure.pages[0].elements[1]
    element.type = "table"
    element.logical_table_id = "table-test"
    element.table = CanonicalTable(row_count=1, col_count=3, cells=[["1", "A", "5"]])
    structure.tables = [LogicalTable(
        logical_table_id="table-test", fragment_element_ids=[element.element_id], start_page=1, end_page=2,
        spans_multiple_pages=True, row_count=99, col_count=2, cells=[["bad"]],
    )]
    report = _relationship_integrity_report(structure)
    assert report.status == "fail"
    codes = {issue.code for issue in report.errors}
    assert "table_page_range_mismatch" in codes
    assert "table_span_flag_mismatch" in codes
    assert "table_column_count_mismatch" in codes
    assert "table_cells_mismatch" in codes


def test_resolved_structure_is_stage5_ready_when_integrity_passes():
    from app.schemas import RelationshipReviewState
    extraction, structure = _structural_fixture()
    artifact = _artifact_for(structure, [])
    first = resolve_structure(automatic=structure, extraction=extraction, corrections=artifact)
    assert first.integrity.status == "pass"
    assert first.review.status == "not_reviewed"
    assert first.review.stage5_eligible is True

    artifact.relationship_review = RelationshipReviewState(
        status="approved", approved_issue_ids=[], approved_at=datetime.now(timezone.utc), note="reviewed"
    )
    approved = resolve_structure(automatic=structure, extraction=extraction, corrections=artifact)
    assert approved.review.status == "approved"
    assert approved.review.stage5_eligible is True


def test_review_required_warning_does_not_block_stage5():
    from app.schemas import RelationshipReviewState
    extraction, structure = _structural_fixture()
    # Automatic orphan subclause: internally valid enough to resolve, but review-required.
    orphan = CanonicalElement(
        element_id="orphan-sub", type="subclause", page_number=1, reading_order=2, document_order=2,
        bbox=[60, 210, 540, 230], text="(a) orphan", section_id="sec-1", clause_id="clause-orphan",
        subclause_marker="(a)", role_source="fixture",
        source=CanonicalSourceTrace(layout_box_index=-1, layout_box_class="list-item", stage3_block_ids=[], stage3_table_ids=[]),
    )
    structure.pages[0].elements.append(orphan)
    structure.sections[0].content_element_ids.append(orphan.element_id)
    structure.clauses.append(ClauseRecord(
        clause_id="clause-orphan", number="(a)", kind="subclause", element_id=orphan.element_id,
        page_number=1, section_id="sec-1", parent_clause_id=None,
    ))
    first = resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, []))
    assert first.integrity.status == "pass"
    assert first.integrity.semantic_status == "review_required"
    warning = next(issue for issue in first.integrity.warnings if issue.code == "subclause_without_parent")
    assert first.review.status == "needs_review"
    assert first.review.stage5_eligible is True

    artifact = _artifact_for(structure, [])
    artifact.relationship_review = RelationshipReviewState(
        status="approved", approved_issue_ids=[warning.issue_id], approved_at=datetime.now(timezone.utc)
    )
    approved = resolve_structure(automatic=structure, extraction=extraction, corrections=artifact)
    assert approved.review.status == "approved"
    assert approved.review.stage5_eligible is True


def test_relationship_provenance_distinguishes_manual_and_derived_edges():
    extraction, structure = _structural_fixture()
    # Base hierarchy is rebuilt as derived.
    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, []))
    derived = next(relation for relation in resolved.structure.relationships if relation.type == "belongs_to")
    assert derived.provenance == "derived"

    # Manual relationship snapshots are converted with explicit manual provenance.
    from app.services.corrections import _relationship_from_spec
    relation = _relationship_from_spec(CorrectionRelationshipSpec(
        relation_id="rel-manual", type="continues", source_element_id="source",
        target_element_id="target", source_page_number=1, target_page_number=2,
        evidence="manual test continuation",
    ))
    assert relation.provenance == "manual"


# Stage 4.5.8.13 — relation-model corrections

def test_orphan_subclauses_are_not_treated_as_siblings_for_duplicate_markers():
    from app.services.corrections import _relationship_integrity_report
    _, structure = _structural_fixture()
    for index, marker in enumerate(("(i)", "(i)"), start=2):
        element = CanonicalElement(
            element_id=f"orphan-{index}", type="subclause", page_number=1,
            reading_order=index, document_order=index, bbox=[60, 200 + 30 * index, 540, 220 + 30 * index],
            text=f"{marker} unrelated item", section_id="sec-1", clause_id=f"orphan-clause-{index}",
            parent_clause_id=None, subclause_marker=marker, role_source="fixture",
            source=CanonicalSourceTrace(layout_box_index=-1, layout_box_class="list-item", stage3_block_ids=[], stage3_table_ids=[]),
        )
        structure.pages[0].elements.append(element)
        structure.sections[0].content_element_ids.append(element.element_id)
        structure.clauses.append(ClauseRecord(
            clause_id=f"orphan-clause-{index}", number=marker, kind="subclause", element_id=element.element_id,
            page_number=1, section_id="sec-1", parent_clause_id=None,
        ))
    report = _relationship_integrity_report(structure)
    assert not any(issue.code == "duplicate_subclause_marker" for issue in report.errors)
    assert sum(issue.code == "subclause_without_parent" for issue in report.warnings) >= 2


def test_table_row_definition_source_is_provenance_not_live_canonical_fk():
    from app.services.corrections import _relationship_integrity_report
    _, structure = _structural_fixture()
    term = CanonicalElement(
        element_id="def-term", type="definition_term", page_number=1, reading_order=2, document_order=2,
        bbox=[60, 240, 250, 260], text="beneficiary", section_id="sec-1", definition_entry_id="def-prov",
        role_source="definition_table_semantic_normalization",
        source=CanonicalSourceTrace(layout_box_index=10, layout_box_class="table", stage3_block_ids=[], stage3_table_ids=[]),
    )
    text = CanonicalElement(
        element_id="def-text", type="definition_text", page_number=1, reading_order=3, document_order=3,
        bbox=[280, 240, 540, 280], text="means a person...", section_id="sec-1", definition_entry_id="def-prov",
        role_source="definition_table_semantic_normalization",
        source=CanonicalSourceTrace(layout_box_index=10, layout_box_class="table", stage3_block_ids=[], stage3_table_ids=[]),
    )
    structure.pages[0].elements.extend([term, text])
    structure.sections[0].content_element_ids.extend([term.element_id, text.element_id])
    structure.definitions = [DefinitionEntry(
        definition_id="def-prov", term="beneficiary", section_id="sec-1", term_element_id=term.element_id,
        source_table_element_id="p1-e11", source_kind="table_rows", definition_text=text.text,
        definition_element_ids=[text.element_id], start_page=1, end_page=1,
    )]
    report = _relationship_integrity_report(structure)
    assert not any(issue.code == "definition_table_source_invalid" for issue in report.errors)


def test_manual_definition_link_inherits_term_section_and_rebuilds_section_membership():
    _, extraction, structure = _fixture()
    term = structure.pages[0].elements[0]
    text = structure.pages[0].elements[1]
    term.type = "definition_term"
    term.definition_entry_id = None
    term.section_id = "sec-def"
    term.heading_level = None
    term.heading_level_source = None
    text.type = "definition_text"
    text.definition_entry_id = None
    text.section_id = None
    structure.sections = [SectionRecord(
        section_id="sec-def", title="Definitions", level=1, page_number=1,
        element_id=term.element_id, level_source="font_rank", content_element_ids=[],
    )]
    # A definition term is not a section header, so use a dedicated header as
    # the section source and keep the term as ordinary section content.
    header = term.model_copy(deep=True)
    header.element_id = "sec-header"
    header.type = "section_header"
    header.section_id = "sec-def"
    header.heading_level = 1
    header.heading_level_source = "font_rank"
    header.document_order = 0
    header.reading_order = 0
    term.document_order = 1
    term.reading_order = 1
    text.document_order = 2
    text.reading_order = 2
    structure.pages[0].elements = [header, term, text]
    structure.sections[0].element_id = header.element_id
    structure.sections[0].content_element_ids = [term.element_id]
    op = CorrectionOperation(
        operation_id="op-def-section-inherit", operation="link_definition", page_number=1,
        source_element_ids=[term.element_id, text.element_id], target_page_number=1,
        created_at=datetime.now(timezone.utc),
    )
    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [op]))
    resolved_text = next(e for e in resolved.structure.pages[0].elements if e.element_id == text.element_id)
    assert resolved_text.section_id == "sec-def"
    assert text.element_id in resolved.structure.sections[0].content_element_ids
    assert resolved.integrity.status == "pass"


def test_adjacent_page_boundary_duplicate_clause_is_review_warning_not_hard_error():
    from app.services.corrections import _relationship_integrity_report
    _, structure = _structural_fixture()
    first = structure.pages[0].elements[1]
    first.clause_number = "11.6"
    first.bbox = [60, 700, 540, 790]
    structure.clauses[0].number = "11.6"
    page2_element = first.model_copy(deep=True)
    page2_element.element_id = "p2-e1"
    page2_element.page_number = 2
    page2_element.reading_order = 0
    page2_element.document_order = 2
    page2_element.bbox = [60, 30, 540, 90]
    page2_element.clause_id = "clause-2"
    structure.pages.append(StructuredPage(page_number=2, width=600, height=800, elements=[page2_element], body_text=page2_element.text))
    structure.sections[0].content_element_ids.append(page2_element.element_id)
    structure.clauses.append(ClauseRecord(
        clause_id="clause-2", number="11.6", kind="clause", element_id=page2_element.element_id,
        page_number=2, section_id="sec-1", parent_clause_id=None,
    ))
    report = _relationship_integrity_report(structure)
    assert not any(issue.code == "duplicate_clause_number" for issue in report.errors)
    warning = next(issue for issue in report.warnings if issue.code == "possible_cross_page_clause_continuation")
    assert warning.requires_review is True


def test_resolved_artifact_exposes_automatic_baseline_integrity_separately():
    extraction, structure = _structural_fixture()
    orphan = CanonicalElement(
        element_id="baseline-orphan", type="subclause", page_number=1, reading_order=2, document_order=2,
        bbox=[60, 220, 540, 240], text="(a) orphan", section_id="sec-1", clause_id="baseline-orphan-clause",
        subclause_marker="(a)", role_source="fixture",
        source=CanonicalSourceTrace(layout_box_index=-1, layout_box_class="list-item", stage3_block_ids=[], stage3_table_ids=[]),
    )
    structure.pages[0].elements.append(orphan)
    structure.sections[0].content_element_ids.append(orphan.element_id)
    structure.clauses.append(ClauseRecord(
        clause_id="baseline-orphan-clause", number="(a)", kind="subclause", element_id=orphan.element_id,
        page_number=1, section_id="sec-1", parent_clause_id=None,
    ))
    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, []))
    assert resolved.baseline_integrity is not None
    assert any(issue.code == "subclause_without_parent" for issue in resolved.baseline_integrity.warnings)
    assert any(issue.code == "subclause_without_parent" for issue in resolved.integrity.warnings)


def test_manual_drawn_definition_text_uses_explicit_definition_assignment():
    _, extraction, structure = _fixture()
    term = structure.pages[0].elements[0]
    existing = structure.pages[0].elements[1]
    header = term.model_copy(deep=True)
    header.element_id = "defs-header"
    header.type = "section_header"
    header.text = "3. DEFINITIONS"
    header.section_id = "sec-def"
    header.definition_entry_id = None
    header.heading_level = 1
    header.heading_level_source = "font_rank"
    header.reading_order = 0
    header.document_order = 0
    header.bbox = [60, 10, 540, 25]

    term.type = "definition_term"
    term.text = "politically exposed person (PEP)"
    term.section_id = "sec-def"
    term.definition_entry_id = "def-pep"
    term.heading_level = None
    term.heading_level_source = None
    term.reading_order = 1
    term.document_order = 1
    term.bbox = [60, 50, 250, 80]

    existing.type = "definition_text"
    existing.text = "(c) person entrusted with an international organisation function"
    existing.section_id = "sec-def"
    existing.definition_entry_id = "def-pep"
    existing.reading_order = 2
    existing.document_order = 2
    existing.bbox = [280, 120, 540, 180]
    structure.pages[0].elements = [header, term, existing]
    structure.sections = [SectionRecord(
        section_id="sec-def", title="3. DEFINITIONS", level=1, page_number=1,
        element_id=header.element_id, level_source="font_rank", content_element_ids=[term.element_id, existing.element_id],
    )]
    structure.definitions = [DefinitionEntry(
        definition_id="def-pep", term=term.text, section_id="sec-def", term_element_id=term.element_id,
        source_kind="layout_columns", definition_text=existing.text,
        definition_element_ids=[existing.element_id], start_page=1, end_page=1,
    )]
    structure.clauses = []
    structure.relationships = []
    extraction.pages[0].blocks.append(_text_block("p1-b3", 3, [280, 190, 540, 240], "(d) person with joint ownership"))
    extraction.pages[0].text += "\n(d) person with joint ownership"

    draw = CorrectionOperation(
        operation_id="op-draw-def-d", operation="draw", page_number=1,
        result_elements=[CorrectionElementSpec(
            element_id="manual-d", type="definition_text", bbox=[280, 190, 540, 240],
        )], created_at=datetime.now(timezone.utc),
    )
    assign = CorrectionOperation(
        operation_id="op-assign-def-d", operation="assign_definition", page_number=1,
        source_element_ids=["manual-d"], definition_id="def-pep",
        created_at=datetime.now(timezone.utc),
    )
    resolved = resolve_structure(automatic=structure, extraction=extraction, corrections=_artifact_for(structure, [draw, assign]))
    manual = next(element for element in resolved.structure.pages[0].elements if element.element_id == "manual-d")
    assert manual.definition_entry_id == "def-pep"
    assert manual.section_id == "sec-def"
    assert manual.role_source == "manual_definition_assign"
    definition = next(entry for entry in resolved.structure.definitions if entry.definition_id == "def-pep")
    assert definition.definition_element_ids == [existing.element_id, "manual-d"]
    assert "manual-d" in resolved.structure.sections[0].content_element_ids

# Stage 4.5.8.14 — nested hierarchy + legacy provenance compatibility

def _legacy_flat_nested_subclause_structure():
    extraction, structure = _structural_fixture()
    base = structure.pages[0].elements[1]
    items = [
        ("sub-a", "clause-a", "(a)", 60, 2),
        ("sub-a-i", "clause-a-i", "(i)", 90, 3),
        ("sub-a-ii", "clause-a-ii", "(ii)", 90, 4),
        ("sub-b", "clause-b", "(b)", 60, 5),
        ("sub-b-i", "clause-b-i", "(i)", 90, 6),
        ("sub-b-ii", "clause-b-ii", "(ii)", 90, 7),
    ]
    for index, (element_id, clause_id, marker, x0, order) in enumerate(items):
        element = CanonicalElement(
            element_id=element_id,
            type="subclause",
            page_number=1,
            reading_order=order,
            document_order=order,
            bbox=[x0, 220 + index * 45, 540, 250 + index * 45],
            text=f"{marker} item {element_id}",
            section_id="sec-1",
            clause_id=clause_id,
            parent_clause_id="clause-1",  # legacy flat parent assignment
            subclause_marker=marker,
            role_source="subclause_marker",
            source=CanonicalSourceTrace(
                layout_box_index=-1,
                layout_box_class="list-item",
                stage3_block_ids=[],
                stage3_table_ids=[],
            ),
        )
        structure.pages[0].elements.append(element)
        structure.sections[0].content_element_ids.append(element_id)
        structure.clauses.append(ClauseRecord(
            clause_id=clause_id,
            number=marker,
            kind="subclause",
            element_id=element_id,
            page_number=1,
            section_id="sec-1",
            parent_clause_id="clause-1",
        ))
    structure.summary.element_count = len(structure.pages[0].elements)
    structure.summary.clause_count = len(structure.clauses)
    return extraction, structure


def test_legacy_flat_nested_subclauses_are_not_auto_reparented():
    extraction, structure = _legacy_flat_nested_subclause_structure()
    resolved = resolve_structure(
        automatic=structure,
        extraction=extraction,
        corrections=_artifact_for(structure, []),
    )
    clause_by_id = {record.clause_id: record for record in resolved.structure.clauses}
    assert all(clause_by_id[clause_id].parent_clause_id == "clause-1" for clause_id in [
        "clause-a", "clause-a-i", "clause-a-ii", "clause-b", "clause-b-i", "clause-b-ii"
    ])
    # Stage 4.5.8.16 deliberately preserves unknown/legacy hierarchy rather
    # than guessing a new parent. Any semantic ambiguity remains visible to the
    # reviewer instead of being silently rewritten.
    assert resolved.baseline_integrity is not None


def test_alphabetic_h_i_j_sequence_is_not_mistaken_for_nested_roman():
    extraction, structure = _structural_fixture()
    for index, marker in enumerate(("(h)", "(i)", "(j)"), start=2):
        element_id = f"alpha-{marker[1]}"
        clause_id = f"clause-{marker[1]}"
        element = CanonicalElement(
            element_id=element_id,
            type="subclause",
            page_number=1,
            reading_order=index,
            document_order=index,
            bbox=[60, 220 + index * 40, 540, 250 + index * 40],
            text=f"{marker} alphabetic item",
            section_id="sec-1",
            clause_id=clause_id,
            parent_clause_id="clause-1",
            subclause_marker=marker,
            role_source="subclause_marker",
            source=CanonicalSourceTrace(
                layout_box_index=-1,
                layout_box_class="list-item",
                stage3_block_ids=[],
                stage3_table_ids=[],
            ),
        )
        structure.pages[0].elements.append(element)
        structure.sections[0].content_element_ids.append(element_id)
        structure.clauses.append(ClauseRecord(
            clause_id=clause_id,
            number=marker,
            kind="subclause",
            element_id=element_id,
            page_number=1,
            section_id="sec-1",
            parent_clause_id="clause-1",
        ))
    resolved = resolve_structure(
        automatic=structure,
        extraction=extraction,
        corrections=_artifact_for(structure, []),
    )
    by_id = {record.clause_id: record for record in resolved.structure.clauses}
    assert by_id["clause-h"].parent_clause_id == "clause-1"
    assert by_id["clause-i"].parent_clause_id == "clause-1"
    assert by_id["clause-j"].parent_clause_id == "clause-1"


def test_legacy_definition_source_table_id_is_migrated_to_table_provenance():
    _, extraction, structure = _fixture()
    term = structure.pages[0].elements[0]
    text = structure.pages[0].elements[1]
    term.type = "definition_term"
    term.text = "beneficiary"
    term.definition_entry_id = "def-legacy"
    term.role_source = "definition_table_semantic_normalization"
    term.heading_level = None
    term.heading_level_source = None
    text.type = "definition_text"
    text.text = "means a person"
    text.definition_entry_id = "def-legacy"
    text.role_source = "definition_table_semantic_normalization"
    structure.sections = []
    term.section_id = None
    text.section_id = None
    structure.definitions = [DefinitionEntry(
        definition_id="def-legacy",
        term=term.text,
        term_element_id=term.element_id,
        source_table_element_id="p1-e99",
        # Deliberately omit source_kind to emulate a pre-1.6 artifact. Pydantic
        # loads it as layout_columns, which 8.14 must migrate in memory.
        definition_text=text.text,
        definition_element_ids=[text.element_id],
        start_page=1,
        end_page=1,
    )]
    resolved = resolve_structure(
        automatic=structure,
        extraction=extraction,
        corrections=_artifact_for(structure, []),
    )
    assert not any(issue.code == "definition_table_source_invalid" for issue in resolved.integrity.errors)
    entry = next(item for item in resolved.structure.definitions if item.definition_id == "def-legacy")
    assert entry.source_kind == "table_rows"


def test_fresh_stage4_clause_builder_creates_nested_roman_parents():
    from app.services.canonical import _build_clause_records
    _, structure = _structural_fixture()
    main = structure.pages[0].elements[1]
    main.document_order = 1
    main.reading_order = 1
    elements = [main]
    specs = [
        ("fresh-a", "(a)", 60, 2),
        ("fresh-a-i", "(i)", 90, 3),
        ("fresh-a-ii", "(ii)", 90, 4),
        ("fresh-b", "(b)", 60, 5),
        ("fresh-b-i", "(i)", 90, 6),
        ("fresh-b-ii", "(ii)", 90, 7),
    ]
    for index, (element_id, marker, x0, order) in enumerate(specs):
        elements.append(CanonicalElement(
            element_id=element_id,
            type="subclause",
            page_number=1,
            reading_order=order,
            document_order=order,
            bbox=[x0, 220 + index * 40, 540, 250 + index * 40],
            text=f"{marker} fresh item",
            section_id="sec-1",
            subclause_marker=marker,
            role_source="subclause_marker",
            source=CanonicalSourceTrace(
                layout_box_index=-1,
                layout_box_class="list-item",
                stage3_block_ids=[],
                stage3_table_ids=[],
            ),
        ))
    records, _ = _build_clause_records(elements, structure.sections)
    by_element = {record.element_id: record for record in records}
    main_id = by_element[main.element_id].clause_id
    assert by_element["fresh-a"].parent_clause_id == main_id
    assert by_element["fresh-a-i"].parent_clause_id == by_element["fresh-a"].clause_id
    assert by_element["fresh-a-ii"].parent_clause_id == by_element["fresh-a"].clause_id
    assert by_element["fresh-b"].parent_clause_id == main_id
    assert by_element["fresh-b-i"].parent_clause_id == by_element["fresh-b"].clause_id
    assert by_element["fresh-b-ii"].parent_clause_id == by_element["fresh-b"].clause_id

# Stage 4.5.8.15 — definition membership completion + strict definition relation integrity

def test_relabelled_definition_run_is_assigned_explicitly_in_one_operation():
    _, extraction, structure = _fixture()

    # Page 1 ends inside an open definition.
    header = structure.pages[0].elements[0]
    intro = structure.pages[0].elements[1]
    header.type = "section_header"
    header.text = "3. DEFINITIONS"
    header.section_id = "sec-def"
    header.heading_level = 1
    header.heading_level_source = "font_rank"
    header.definition_entry_id = None
    header.bbox = [60, 40, 220, 60]
    header.reading_order = 0
    header.document_order = 0

    term = intro.model_copy(deep=True)
    term.element_id = "p1-term"
    term.type = "definition_term"
    term.text = "designated person related party"
    term.section_id = "sec-def"
    term.definition_entry_id = "def-open"
    term.bbox = [80, 680, 250, 700]
    term.reading_order = 1
    term.document_order = 1

    first_text = intro.model_copy(deep=True)
    first_text.element_id = "p1-def-intro"
    first_text.type = "definition_text"
    first_text.text = "means—"
    first_text.section_id = "sec-def"
    first_text.definition_entry_id = "def-open"
    first_text.bbox = [310, 735, 540, 790]
    first_text.reading_order = 2
    first_text.document_order = 2
    structure.pages[0].elements = [header, term, first_text]
    structure.pages[0].body_text = "3. DEFINITIONS\n\ndesignated person related party\n\nmeans—"
    structure.sections = [SectionRecord(
        section_id="sec-def", title="3. DEFINITIONS", level=1, page_number=1,
        element_id=header.element_id, level_source="font_rank",
        content_element_ids=[term.element_id, first_text.element_id],
    )]
    structure.definitions = [DefinitionEntry(
        definition_id="def-open", term=term.text, section_id="sec-def",
        term_element_id=term.element_id, source_kind="layout_columns",
        definition_text=first_text.text, definition_element_ids=[first_text.element_id],
        start_page=1, end_page=1, spans_multiple_pages=False,
        continues_to_next_page=True,
    )]
    structure.clauses = []
    structure.relationships = []

    # Page 2 contains the enumerated meaning, but Stage 4 originally classified
    # the rows as list items. The reviewer only relabels them to definition_text.
    page2_blocks = [
        _text_block("p2-b1", 1, [310, 70, 540, 120], "(a) person acting on behalf of a designated person;"),
        _text_block("p2-b2", 2, [310, 135, 540, 185], "(b) person providing support for prohibited activities;"),
        _text_block("p2-b3", 3, [310, 200, 540, 250], "(c) person assisting a designated person; and"),
        _text_block("p2-b4", 4, [310, 265, 540, 315], "(d) person with joint ownership of assets."),
    ]
    extraction.pages.append(PageExtraction(
        page_number=2, width=600, height=800, rotation=0,
        text="\n".join(block.text for block in page2_blocks),
        text_char_count=sum(len(block.text) for block in page2_blocks),
        blocks=page2_blocks, tables=[], warnings=[],
    ))
    extraction.summary.page_count = 2
    extraction.summary.text_block_count += len(page2_blocks)

    page2_elements = []
    for index, block in enumerate(page2_blocks):
        page2_elements.append(CanonicalElement(
            element_id=f"p2-e{index + 1}", type="list_item", page_number=2,
            reading_order=index, document_order=3 + index, bbox=list(block.bbox), text=block.text,
            section_id="sec-def", role_source="layout",
            source=CanonicalSourceTrace(layout_box_index=index, layout_box_class="list-item", stage3_block_ids=[block.block_id]),
        ))
    structure.pages.append(StructuredPage(
        page_number=2, width=600, height=800, elements=page2_elements,
        body_text="\n\n".join(element.text for element in page2_elements),
    ))
    structure.sections[0].content_element_ids.extend(element.element_id for element in page2_elements)

    operations = [CorrectionOperation(
        operation_id="op-relabel-definition-run", operation="relabel", page_number=2,
        source_element_ids=[element.element_id for element in page2_elements], new_type="definition_text",
        created_at=datetime.now(timezone.utc),
    )]
    operations.append(CorrectionOperation(
        operation_id="op-assign-definition-run", operation="assign_definition", page_number=2,
        source_element_ids=[element.element_id for element in page2_elements], definition_id="def-open",
        created_at=datetime.now(timezone.utc),
    ))
    resolved = resolve_structure(
        automatic=structure,
        extraction=extraction,
        corrections=_artifact_for(structure, operations),
    )

    corrected = resolved.structure.pages[1].elements
    assert all(element.type == "definition_text" for element in corrected)
    assert all(element.definition_entry_id == "def-open" for element in corrected)
    assert all(element.section_id == "sec-def" for element in corrected)
    entry = next(entry for entry in resolved.structure.definitions if entry.definition_id == "def-open")
    assert entry.definition_element_ids == [first_text.element_id, *[element.element_id for element in corrected]]
    section = next(section for section in resolved.structure.sections if section.section_id == "sec-def")
    assert all(element.element_id in section.content_element_ids for element in corrected)
    assert entry.start_page == 1
    assert entry.end_page == 2
    assert entry.spans_multiple_pages is True
    assert resolved.integrity.status == "pass"
    assert not any(issue.code == "definition_member_unlinked" for issue in resolved.integrity.errors)


def test_unlinked_definition_text_is_blocking_integrity_error():
    from app.services.corrections import _relationship_integrity_report

    _, _, structure = _fixture()
    element = structure.pages[0].elements[1]
    element.type = "definition_text"
    element.definition_entry_id = None
    structure.definitions = []

    report = _relationship_integrity_report(structure)
    issue = next(issue for issue in report.errors if issue.code == "definition_member_unlinked")
    assert element.element_id in issue.element_ids
    assert report.status == "fail"


def test_resolver_repairs_legacy_overbroad_definition_span_provenance():
    _, extraction, structure = _fixture()
    line = TextLine(
        line_id="p1-b99-l1",
        bbox=[100, 200, 550, 220],
        text="alpha means the first control",
        spans=[
            TextSpan(span_id="p1-b99-l1-s1", text="alpha", bbox=[100, 200, 160, 220], font="Test", size=11),
            TextSpan(span_id="p1-b99-l1-s2", text="means the first control", bbox=[300, 200, 550, 220], font="Test", size=11),
        ],
    )
    extraction.pages[0].blocks = [TextBlock(
        block_id="p1-b99", number=99, bbox=[100, 200, 550, 220],
        text=line.text, lines=[line],
    )]

    broad_trace = CanonicalSourceTrace(
        layout_box_index=4,
        layout_box_class="text",
        stage3_block_ids=["p1-b99"],
        stage3_line_ids=["p1-b99-l1"],
        stage3_span_ids=["p1-b99-l1-s1", "p1-b99-l1-s2"],
        stage3_table_ids=[],
    )
    term = CanonicalElement(
        element_id="term-alpha", type="definition_term", page_number=1,
        reading_order=0, document_order=0, bbox=[100, 200, 160, 220], text="alpha",
        definition_entry_id="def-alpha", role_source="definition_row_recovery_span_columns",
        source=broad_trace.model_copy(deep=True),
    )
    text = CanonicalElement(
        element_id="text-alpha", type="definition_text", page_number=1,
        reading_order=1, document_order=1, bbox=[300, 200, 550, 220], text="means the first control",
        definition_entry_id="def-alpha", role_source="definition_row_recovery_span_columns",
        source=broad_trace.model_copy(deep=True),
    )
    structure.pages[0].elements = [term, text]
    structure.pages[0].body_text = f"{term.text}\n\n{text.text}"
    structure.sections = []
    structure.definitions = [DefinitionEntry(
        definition_id="def-alpha", term=term.text, term_element_id=term.element_id,
        source_kind="layout_columns", definition_text=text.text,
        definition_element_ids=[text.element_id], start_page=1, end_page=1,
    )]
    structure.clauses = []
    structure.relationships = []

    resolved = resolve_structure(
        automatic=structure,
        extraction=extraction,
        corrections=_artifact_for(structure, []),
    )
    resolved_term, resolved_text = resolved.structure.pages[0].elements
    assert resolved_term.source.stage3_span_ids == ["p1-b99-l1-s1"]
    assert resolved_text.source.stage3_span_ids == ["p1-b99-l1-s2"]
    assert set(resolved_term.source.stage3_span_ids).isdisjoint(resolved_text.source.stage3_span_ids)

# Stage 4.5.8.16 — explicit, simplified definition assignment

def test_manual_definition_text_is_not_guessed_without_explicit_assignment():
    _, extraction, structure = _fixture()
    term = structure.pages[0].elements[0]
    text = structure.pages[0].elements[1]
    term.type = "definition_term"
    term.definition_entry_id = "def-explicit"
    term.heading_level = None
    term.heading_level_source = None
    text.type = "definition_text"
    text.definition_entry_id = "def-explicit"
    structure.definitions = [DefinitionEntry(
        definition_id="def-explicit",
        term=term.text,
        term_element_id=term.element_id,
        source_kind="layout_columns",
        definition_text=text.text,
        definition_element_ids=[text.element_id],
        start_page=1,
        end_page=1,
    )]
    extraction.pages[0].blocks.append(_text_block("p1-explicit", 99, [280, 210, 540, 250], "(d) explicit selection required"))
    operation = CorrectionOperation(
        operation_id="op-draw-unassigned",
        operation="draw",
        page_number=1,
        result_elements=[CorrectionElementSpec(
            element_id="manual-unassigned",
            type="definition_text",
            bbox=[280, 210, 540, 250],
        )],
        created_at=datetime.now(timezone.utc),
    )
    resolved = resolve_structure(
        automatic=structure,
        extraction=extraction,
        corrections=_artifact_for(structure, [operation]),
    )
    manual = next(item for item in resolved.structure.pages[0].elements if item.element_id == "manual-unassigned")
    assert manual.definition_entry_id is None
    assert any(
        issue.code == "definition_member_unlinked" and manual.element_id in issue.element_ids
        for issue in resolved.integrity.errors
    )
