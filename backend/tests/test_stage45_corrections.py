from datetime import datetime, timezone
from pathlib import Path

import pymupdf
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.schemas import (
    CanonicalElement,
    CanonicalSourceTrace,
    CorrectionArtifact,
    CorrectionElementSpec,
    CorrectionOperation,
    CorrectionRelationshipSpec,
    DocumentClassification,
    DocumentExtraction,
    DocumentRecord,
    ExtractionSummary,
    ExtractorInfo,
    PageExtraction,
    StructuralRelation,
    StructuredPage,
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

    # Re-running Stage 4 invalidates the manual layer because automatic element IDs may change.
    assert client.post(f"/api/documents/{document_id}/structure").status_code == 200
    assert client.get(f"/api/documents/{document_id}/corrections").status_code == 404
    assert client.get(f"/api/documents/{document_id}/resolved-structure").status_code == 404
