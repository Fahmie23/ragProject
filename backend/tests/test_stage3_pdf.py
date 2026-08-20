from datetime import datetime, timezone
from pathlib import Path
import hashlib

import pymupdf

from app.schemas import DocumentRecord
from app.services.classification import classify_document
from app.services.extraction import extract_document


def _record(path: Path, document_id: str = "test") -> DocumentRecord:
    payload = path.read_bytes()
    classification = classify_document(path, ".pdf")
    return DocumentRecord(
        document_id=document_id,
        original_filename=path.name,
        stored_filename=path.name,
        extension=".pdf",
        detected_mime_type="application/pdf",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        validation_status="valid",
        classification=classification,
        ingested_at=datetime.now(timezone.utc),
    )


def test_digital_pdf_extracts_text_blocks_and_table(tmp_path: Path):
    path = tmp_path / "digital.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "RAG Extraction Test", fontsize=18)
    page.insert_text((72, 110), "Deterministic extraction keeps parser facts separate from Stage 4.", fontsize=11)

    x0, y0, cell_w, cell_h = 72, 160, 120, 30
    for i in range(3):
        page.draw_line((x0 + i * cell_w, y0), (x0 + i * cell_w, y0 + 2 * cell_h))
    for j in range(3):
        page.draw_line((x0, y0 + j * cell_h), (x0 + 2 * cell_w, y0 + j * cell_h))
    page.insert_text((80, 180), "A1", fontsize=10)
    page.insert_text((200, 180), "B1", fontsize=10)
    page.insert_text((80, 210), "A2", fontsize=10)
    page.insert_text((200, 210), "B2", fontsize=10)
    doc.save(path)
    doc.close()

    record = _record(path)
    result = extract_document(path, record)

    assert record.classification.pdf_type == "digital"
    assert result.summary.page_count == 1
    assert result.summary.text_char_count > 0
    assert result.summary.text_block_count >= 2
    assert result.summary.table_count == 1
    assert result.pages[0].tables[0].cells == [["A1", "B1"], ["A2", "B2"]]
    assert result.extractor.settings["ocr"] is False


def test_scanned_pdf_stays_unocred_and_warns(tmp_path: Path):
    text_pdf = tmp_path / "source.pdf"
    source = pymupdf.open()
    source_page = source.new_page()
    source_page.insert_text((72, 72), "Rendered into an image")
    source.save(text_pdf)
    source.close()

    source = pymupdf.open(text_pdf)
    png = source[0].get_pixmap().tobytes("png")
    source.close()

    scan_path = tmp_path / "scan.pdf"
    scan = pymupdf.open()
    scan_page = scan.new_page()
    scan_page.insert_image(scan_page.rect, stream=png)
    scan.save(scan_path)
    scan.close()

    record = _record(scan_path, "scan")
    result = extract_document(scan_path, record)

    assert record.classification.pdf_type == "scanned"
    assert result.extraction_mode == "visual_only_no_ocr"
    assert result.summary.text_char_count == 0
    assert result.summary.image_block_count >= 1
    assert result.warnings
    assert any("No extractable text layer" in warning for warning in result.pages[0].warnings)
