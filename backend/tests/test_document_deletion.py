from __future__ import annotations

from pathlib import Path

import pymupdf
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def _pdf_bytes() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((40, 60), "Delete lifecycle test")
    payload = doc.tobytes()
    doc.close()
    return payload


def test_delete_document_removes_all_runtime_files_but_not_curated_assets(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "database_url", None)
    for directory in (
        settings.raw_dir, settings.metadata_dir, settings.extracted_dir, settings.layout_dir,
        settings.structured_dir, settings.corrections_dir, settings.resolved_dir, settings.chunks_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    curated = tmp_path / "evaluation" / "golden" / "keep.json"
    curated.parent.mkdir(parents=True)
    curated.write_text('{"keep": true}', encoding="utf-8")

    client = TestClient(app)
    upload = client.post("/api/documents/upload", files={"file": ("sample.pdf", _pdf_bytes(), "application/pdf")})
    assert upload.status_code == 200
    record = upload.json()["document"]
    document_id = record["document_id"]

    for directory in (settings.extracted_dir, settings.layout_dir, settings.structured_dir, settings.corrections_dir, settings.resolved_dir, settings.chunks_dir):
        (directory / f"{document_id}.json").write_text("{}", encoding="utf-8")

    response = client.delete(f"/api/documents/{document_id}")
    assert response.status_code == 204
    assert client.get(f"/api/documents/{document_id}").status_code == 404
    assert not (settings.raw_dir / record["stored_filename"]).exists()
    for directory in (settings.metadata_dir, settings.extracted_dir, settings.layout_dir, settings.structured_dir, settings.corrections_dir, settings.resolved_dir, settings.chunks_dir):
        assert not (directory / f"{document_id}.json").exists()
    assert curated.exists()


def test_delete_missing_document_returns_404(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "database_url", None)
    settings.metadata_dir.mkdir(parents=True, exist_ok=True)
    response = TestClient(app).delete("/api/documents/missing")
    assert response.status_code == 404
