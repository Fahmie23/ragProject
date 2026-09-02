from __future__ import annotations

from pathlib import Path

import pymupdf
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def _pdf_bytes() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "Stage 12 System Test", fontsize=20)
    page.insert_text((72, 120), "1 Scope", fontsize=15)
    page.insert_text((72, 155), "The reporting institution shall keep records.", fontsize=11)
    payload = doc.tobytes()
    doc.close()
    return payload


def _layout_artifact() -> dict:
    return {
        "engine": {"name": "PyMuPDF4LLM Layout", "version": "1.28.0-test", "settings": {"use_layout": True, "use_ocr": False}},
        "result": {
            "filename": "stage12.pdf",
            "page_count": 1,
            "toc": [[1, "1 Scope", 1]],
            "pages": [
                {
                    "page_number": 1,
                    "width": 595,
                    "height": 842,
                    "boxes": [
                        {"x0": 70, "y0": 50, "x1": 360, "y1": 82, "boxclass": "title", "textlines": [{"spans": [{"text": "Stage 12 System Test"}]}]},
                        {"x0": 70, "y0": 100, "x1": 300, "y1": 132, "boxclass": "section-header", "textlines": [{"spans": [{"text": "1 Scope"}]}]},
                        {"x0": 70, "y0": 140, "x1": 520, "y1": 178, "boxclass": "text", "textlines": [{"spans": [{"text": "The reporting institution shall keep records."}]}]},
                    ],
                }
            ],
        },
    }


def _prepare_dirs(tmp_path: Path, monkeypatch) -> None:
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


def _build_to_chunks(tmp_path: Path, monkeypatch) -> tuple[TestClient, str]:
    _prepare_dirs(tmp_path, monkeypatch)
    monkeypatch.setattr("app.services.structure.analyze_pdf_layout", lambda path: _layout_artifact())
    client = TestClient(app)
    upload = client.post("/api/documents/upload", files={"file": ("stage12.pdf", _pdf_bytes(), "application/pdf")})
    assert upload.status_code == 200
    document_id = upload.json()["document"]["document_id"]
    assert client.post(f"/api/documents/{document_id}/extract").status_code == 200
    structure = client.post(f"/api/documents/{document_id}/structure")
    assert structure.status_code == 200
    base_structured_at = structure.json()["structured_at"]
    save = client.put(
        f"/api/documents/{document_id}/corrections",
        json={"base_structured_at": base_structured_at, "operations": []},
    )
    assert save.status_code == 200
    assert save.json()["resolved"]["integrity"]["status"] == "pass"
    chunks = client.post(f"/api/documents/{document_id}/chunks", json={})
    assert chunks.status_code == 200
    assert chunks.json()["chunks"]
    return client, document_id


def test_end_to_end_file_pipeline_and_upstream_invalidation(tmp_path: Path, monkeypatch):
    client, document_id = _build_to_chunks(tmp_path, monkeypatch)

    assert client.get(f"/api/documents/{document_id}").status_code == 200
    assert client.get(f"/api/documents/{document_id}/file").content.startswith(b"%PDF")
    assert client.get(f"/api/documents/{document_id}/extraction").status_code == 200
    assert client.get(f"/api/documents/{document_id}/structure").status_code == 200
    assert client.get(f"/api/documents/{document_id}/resolved-structure").status_code == 200
    assert client.get(f"/api/documents/{document_id}/chunks").status_code == 200

    # Stage 3 is upstream of Stage 4/4.5/5. A successful re-extraction must make
    # every downstream artifact unavailable rather than serving stale content.
    rerun = client.post(f"/api/documents/{document_id}/extract")
    assert rerun.status_code == 200
    assert client.get(f"/api/documents/{document_id}/structure").status_code == 404
    assert client.get(f"/api/documents/{document_id}/corrections").status_code == 404
    assert client.get(f"/api/documents/{document_id}/resolved-structure").status_code == 404
    assert client.get(f"/api/documents/{document_id}/chunks").status_code == 404


def test_stage5_stale_artifact_is_failed_closed_and_removed(tmp_path: Path, monkeypatch):
    client, document_id = _build_to_chunks(tmp_path, monkeypatch)

    resolved_path = settings.resolved_dir / f"{document_id}.json"
    assert resolved_path.exists()
    resolved_path.unlink()

    stale = client.get(f"/api/documents/{document_id}/chunks")
    assert stale.status_code == 409
    assert "stale" in stale.json()["detail"].lower()
    assert client.get(f"/api/documents/{document_id}/chunks").status_code == 404


def test_missing_raw_file_fails_closed_after_metadata_exists(tmp_path: Path, monkeypatch):
    _prepare_dirs(tmp_path, monkeypatch)
    client = TestClient(app)
    upload = client.post("/api/documents/upload", files={"file": ("stage12.pdf", _pdf_bytes(), "application/pdf")})
    assert upload.status_code == 200
    record = upload.json()["document"]
    (settings.raw_dir / record["stored_filename"]).unlink()

    assert client.get(f"/api/documents/{record['document_id']}/file").status_code == 404
    assert client.post(f"/api/documents/{record['document_id']}/extract").status_code == 404


def test_upload_size_limit_returns_413_without_persisting_metadata(tmp_path: Path, monkeypatch):
    _prepare_dirs(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "max_upload_mb", 0)
    client = TestClient(app)
    response = client.post("/api/documents/upload", files={"file": ("stage12.pdf", _pdf_bytes(), "application/pdf")})
    assert response.status_code == 413
    assert client.get("/api/documents").json() == []
