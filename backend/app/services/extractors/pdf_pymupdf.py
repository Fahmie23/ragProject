from datetime import datetime, timezone
from pathlib import Path

import pymupdf

from app.schemas import (
    DocumentExtraction,
    DocumentRecord,
    ExtractionSummary,
    ExtractorInfo,
    ImageBlock,
    PageExtraction,
    TableExtraction,
    TextBlock,
    TextLine,
    TextSpan,
)


def _bbox(value) -> list[float]:
    return [round(float(v), 3) for v in value]


def _point(value) -> list[float] | None:
    if value is None:
        return None
    return [round(float(v), 3) for v in value]


def _text_from_line(line: dict) -> str:
    return "".join(span.get("text", "") for span in line.get("spans", []))


def _parse_text_block(page_number: int, block: dict) -> TextBlock:
    lines: list[TextLine] = []
    block_number = int(block.get("number", 0))
    block_id = f"p{page_number}-b{block_number}"

    for line_index, line in enumerate(block.get("lines", [])):
        line_id = f"{block_id}-l{line_index + 1}"
        spans: list[TextSpan] = []
        for span_index, span in enumerate(line.get("spans", [])):
            spans.append(
                TextSpan(
                    span_id=f"{line_id}-s{span_index + 1}",
                    text=span.get("text", ""),
                    bbox=_bbox(span.get("bbox", (0, 0, 0, 0))),
                    origin=_point(span.get("origin")),
                    font=span.get("font"),
                    size=round(float(span["size"]), 3) if span.get("size") is not None else None,
                    flags=span.get("flags"),
                    color=span.get("color"),
                    ascender=round(float(span["ascender"]), 3) if span.get("ascender") is not None else None,
                    descender=round(float(span["descender"]), 3) if span.get("descender") is not None else None,
                )
            )
        lines.append(
            TextLine(
                line_id=line_id,
                bbox=_bbox(line.get("bbox", (0, 0, 0, 0))),
                text=_text_from_line(line),
                writing_mode=line.get("wmode"),
                direction=_point(line.get("dir")),
                spans=spans,
            )
        )

    return TextBlock(
        block_id=block_id,
        number=block_number,
        bbox=_bbox(block.get("bbox", (0, 0, 0, 0))),
        text="\n".join(line.text for line in lines).strip(),
        lines=lines,
    )


def _parse_image_block(page_number: int, block: dict) -> ImageBlock:
    block_number = int(block.get("number", 0))
    return ImageBlock(
        block_id=f"p{page_number}-b{block_number}",
        number=block_number,
        bbox=_bbox(block.get("bbox", (0, 0, 0, 0))),
        width=block.get("width"),
        height=block.get("height"),
        extension=block.get("ext"),
        colorspace=block.get("colorspace"),
        bits_per_component=block.get("bpc"),
        xres=block.get("xres"),
        yres=block.get("yres"),
        encoded_size_bytes=block.get("size"),
    )


def _extract_tables(page, page_number: int) -> tuple[list[TableExtraction], list[str]]:
    tables: list[TableExtraction] = []
    warnings: list[str] = []

    try:
        finder = page.find_tables()
    except Exception as exc:
        return [], [f"Table detection failed on page {page_number}: {exc}"]

    for index, table in enumerate(finder.tables, start=1):
        try:
            bbox = _bbox(table.bbox)
            cells = table.extract()
            tables.append(
                TableExtraction(
                    table_id=f"p{page_number}-t{index}",
                    bbox=bbox,
                    row_count=int(table.row_count),
                    col_count=int(table.col_count),
                    cells=cells,
                )
            )
        except Exception as exc:
            warnings.append(f"Skipped table {index} on page {page_number}: {exc}")

    return tables, warnings


def _extraction_mode(record: DocumentRecord) -> str:
    pdf_type = record.classification.pdf_type
    if pdf_type == "digital":
        return "text_layer"
    if pdf_type == "mixed":
        return "partial_text_layer"
    if pdf_type == "scanned":
        return "visual_only_no_ocr"
    return "best_effort"


def extract_pdf(path: Path, record: DocumentRecord) -> DocumentExtraction:
    document_warnings: list[str] = []

    if record.classification.pdf_type == "scanned":
        document_warnings.append(
            "This PDF is classified as scanned. Stage 3 does not run OCR, so text extraction may be empty."
        )
    elif record.classification.pdf_type == "mixed":
        document_warnings.append(
            "This PDF is classified as mixed. Pages without a text layer will remain un-OCRed in Stage 3."
        )

    doc = pymupdf.open(path)
    pages: list[PageExtraction] = []
    total_text_chars = 0
    total_text_blocks = 0
    total_image_blocks = 0
    total_tables = 0

    try:
        for page_index, page in enumerate(doc):
            page_number = page_index + 1
            page_dict = page.get_text("dict", sort=True)
            page_text = page.get_text("text", sort=True).strip()

            parsed_blocks: list[TextBlock | ImageBlock] = []
            for block in page_dict.get("blocks", []):
                block_type = block.get("type")
                if block_type == 0:
                    parsed_blocks.append(_parse_text_block(page_number, block))
                    total_text_blocks += 1
                elif block_type == 1:
                    parsed_blocks.append(_parse_image_block(page_number, block))
                    total_image_blocks += 1

            tables, table_warnings = _extract_tables(page, page_number)
            total_tables += len(tables)
            total_text_chars += len(page_text)

            page_warnings = list(table_warnings)
            if not page_text and record.classification.pdf_type in {"scanned", "mixed"}:
                page_warnings.append("No extractable text layer detected on this page.")

            pages.append(
                PageExtraction(
                    page_number=page_number,
                    width=round(float(page.rect.width), 3),
                    height=round(float(page.rect.height), 3),
                    rotation=int(page.rotation),
                    text=page_text,
                    text_char_count=len(page_text),
                    blocks=parsed_blocks,
                    tables=tables,
                    warnings=page_warnings,
                )
            )
    finally:
        doc.close()

    return DocumentExtraction(
        document_id=record.document_id,
        source_filename=record.original_filename,
        source_sha256=record.sha256,
        source_pdf_type=record.classification.pdf_type,
        extraction_mode=_extraction_mode(record),
        extractor=ExtractorInfo(
            name="PyMuPDF",
            version=str(getattr(pymupdf, "VersionBind", "unknown")),
            settings={
                "text_output": "dict + text",
                "sort": True,
                "table_detection": True,
                "ocr": False,
            },
        ),
        summary=ExtractionSummary(
            page_count=len(pages),
            text_char_count=total_text_chars,
            text_block_count=total_text_blocks,
            image_block_count=total_image_blocks,
            table_count=total_tables,
        ),
        pages=pages,
        warnings=document_warnings,
        extracted_at=datetime.now(timezone.utc),
    )
