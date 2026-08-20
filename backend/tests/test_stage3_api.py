from pathlib import Path

import pymupdf
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def _pdf_bytes() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "API integration test", fontsize=16)
    page.insert_text((72, 105), "Stage 3 returns deterministic extraction JSON.", fontsize=11)
    payload = doc.tobytes()
    doc.close()
    return payload


def test_upload_extract_fetch_and_preview(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    settings.metadata_dir.mkdir(parents=True, exist_ok=True)
    settings.extracted_dir.mkdir(parents=True, exist_ok=True)

    client = TestClient(app)
    upload = client.post(
        "/api/documents/upload",
        files={"file": ("sample.pdf", _pdf_bytes(), "application/pdf")},
    )
    assert upload.status_code == 200
    record = upload.json()["document"]
    document_id = record["document_id"]
    assert record["validation_status"] == "valid"
    assert record["classification"]["pdf_type"] == "digital"
    assert record["extraction_status"] == "not_started"

    extraction = client.post(f"/api/documents/{document_id}/extract")
    assert extraction.status_code == 200
    result = extraction.json()
    assert result["summary"]["page_count"] == 1
    assert result["summary"]["text_char_count"] > 0
    assert result["pages"][0]["blocks"]

    fetched = client.get(f"/api/documents/{document_id}/extraction")
    assert fetched.status_code == 200
    assert fetched.json()["document_id"] == document_id

    refreshed = client.get(f"/api/documents/{document_id}")
    assert refreshed.status_code == 200
    assert refreshed.json()["extraction_status"] == "completed"

    preview = client.get(f"/api/documents/{document_id}/pages/1/preview")
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/png")
    assert preview.content.startswith(b"\x89PNG")
