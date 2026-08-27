from pathlib import Path

import pymupdf
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def _pdf_bytes() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "Sample Report", fontsize=20)
    page.insert_text((72, 120), "1 Introduction", fontsize=15)
    page.insert_text((72, 155), "Stage 4 API integration test body.", fontsize=11)
    payload = doc.tobytes()
    doc.close()
    return payload


def _layout_artifact() -> dict:
    return {
        "engine": {
            "name": "PyMuPDF4LLM Layout",
            "version": "1.28.0-test",
            "settings": {"use_layout": True, "use_ocr": False},
        },
        "result": {
            "filename": "sample.pdf",
            "page_count": 1,
            "toc": [[1, "1 Introduction", 1]],
            "pages": [
                {
                    "page_number": 1,
                    "width": 595,
                    "height": 842,
                    "boxes": [
                        {
                            "x0": 70, "y0": 50, "x1": 300, "y1": 80,
                            "boxclass": "title",
                            "textlines": [{"spans": [{"text": "Sample Report"}]}],
                        },
                        {
                            "x0": 70, "y0": 100, "x1": 300, "y1": 130,
                            "boxclass": "section-header",
                            "textlines": [{"spans": [{"text": "1 Introduction"}]}],
                        },
                        {
                            "x0": 70, "y0": 135, "x1": 500, "y1": 175,
                            "boxclass": "text",
                            "textlines": [{"spans": [{"text": "Stage 4 API integration test body."}]}],
                        },
                    ],
                }
            ],
        },
    }


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
    ):
        directory.mkdir(parents=True, exist_ok=True)


def test_stage4_requires_stage3(tmp_path: Path, monkeypatch):
    _prepare_dirs(tmp_path, monkeypatch)
    client = TestClient(app)
    upload = client.post(
        "/api/documents/upload",
        files={"file": ("sample.pdf", _pdf_bytes(), "application/pdf")},
    )
    document_id = upload.json()["document"]["document_id"]

    response = client.post(f"/api/documents/{document_id}/structure")
    assert response.status_code == 400
    assert "Stage 3" in response.json()["detail"]


def test_upload_extract_structure_fetch_and_invalidate(tmp_path: Path, monkeypatch):
    _prepare_dirs(tmp_path, monkeypatch)
    monkeypatch.setattr("app.services.structure.analyze_pdf_layout", lambda path: _layout_artifact())

    client = TestClient(app)
    upload = client.post(
        "/api/documents/upload",
        files={"file": ("sample.pdf", _pdf_bytes(), "application/pdf")},
    )
    assert upload.status_code == 200
    document_id = upload.json()["document"]["document_id"]

    extraction = client.post(f"/api/documents/{document_id}/extract")
    assert extraction.status_code == 200

    structure = client.post(f"/api/documents/{document_id}/structure")
    assert structure.status_code == 200
    payload = structure.json()
    assert payload["title"] == "Sample Report"
    assert payload["summary"]["section_count"] == 1
    assert payload["pages"][0]["elements"][0]["type"] == "title"

    layout = client.get(f"/api/documents/{document_id}/layout")
    assert layout.status_code == 200
    assert layout.json()["engine"]["name"] == "PyMuPDF4LLM Layout"

    refreshed = client.get(f"/api/documents/{document_id}")
    assert refreshed.json()["structure_status"] == "completed"

    # Re-running Stage 3 invalidates Stage 4 artifacts and metadata.
    rerun = client.post(f"/api/documents/{document_id}/extract")
    assert rerun.status_code == 200
    refreshed = client.get(f"/api/documents/{document_id}")
    assert refreshed.json()["structure_status"] == "not_started"
    assert client.get(f"/api/documents/{document_id}/structure").status_code == 404
    assert client.get(f"/api/documents/{document_id}/layout").status_code == 404


def test_correction_validation_is_non_persistent_and_save_requires_integrity_pass(tmp_path: Path, monkeypatch):
    _prepare_dirs(tmp_path, monkeypatch)
    monkeypatch.setattr("app.services.structure.analyze_pdf_layout", lambda path: _layout_artifact())
    client = TestClient(app)
    upload = client.post(
        "/api/documents/upload",
        files={"file": ("sample.pdf", _pdf_bytes(), "application/pdf")},
    )
    document_id = upload.json()["document"]["document_id"]
    assert client.post(f"/api/documents/{document_id}/extract").status_code == 200
    structure_response = client.post(f"/api/documents/{document_id}/structure")
    assert structure_response.status_code == 200
    structure = structure_response.json()
    section_id = structure["sections"][0]["section_id"]
    body = next(element for element in structure["pages"][0]["elements"] if element["type"] == "paragraph")
    payload = {
        "base_structured_at": structure["structured_at"],
        "operations": [{
            "operation_id": "op-api-structure",
            "operation": "set_structure",
            "page_number": 1,
            "source_element_ids": [body["element_id"]],
            "result_elements": [],
            "relationships": [],
            "structure": {
                "element_id": body["element_id"],
                "type": "clause",
                "section_id": section_id,
                "clause_id": "manual-clause-api",
                "clause_number": "1.1",
            },
            "created_at": structure["structured_at"],
        }],
    }

    validate = client.post(f"/api/documents/{document_id}/corrections/validate", json=payload)
    assert validate.status_code == 200
    assert validate.json()["valid"] is True
    assert validate.json()["resolved"]["integrity"]["status"] == "pass"
    assert client.get(f"/api/documents/{document_id}/corrections").status_code == 404

    save = client.put(f"/api/documents/{document_id}/corrections", json=payload)
    assert save.status_code == 200
    assert save.json()["resolved"]["integrity"]["status"] == "pass"
    assert any(clause["clause_id"] == "manual-clause-api" for clause in save.json()["resolved"]["structure"]["clauses"])
    assert client.get(f"/api/documents/{document_id}/corrections").status_code == 200


def test_zero_correction_review_can_be_finalized_for_stage5(tmp_path: Path, monkeypatch):
    _prepare_dirs(tmp_path, monkeypatch)
    monkeypatch.setattr("app.services.structure.analyze_pdf_layout", lambda path: _layout_artifact())
    client = TestClient(app)
    upload = client.post(
        "/api/documents/upload",
        files={"file": ("sample.pdf", _pdf_bytes(), "application/pdf")},
    )
    document_id = upload.json()["document"]["document_id"]
    assert client.post(f"/api/documents/{document_id}/extract").status_code == 200
    structure_response = client.post(f"/api/documents/{document_id}/structure")
    assert structure_response.status_code == 200
    structure = structure_response.json()

    save = client.put(
        f"/api/documents/{document_id}/corrections",
        json={"base_structured_at": structure["structured_at"], "operations": []},
    )
    assert save.status_code == 200
    assert save.json()["resolved"]["correction_count"] == 0
    assert save.json()["resolved"]["integrity"]["status"] == "pass"
    assert save.json()["resolved"]["review"]["stage5_eligible"] is True
