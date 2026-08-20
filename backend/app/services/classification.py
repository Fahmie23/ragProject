from pathlib import Path

import pymupdf

from app.schemas import DocumentClassification


MIN_TEXT_CHARS_PER_PAGE = 50


def classify_document(path: Path, extension: str) -> DocumentClassification:
    extension = extension.lower()

    if extension == ".pdf":
        return classify_pdf(path)

    family_map = {
        ".docx": "word",
        ".txt": "text",
        ".md": "markdown",
        ".html": "html",
        ".htm": "html",
    }

    return DocumentClassification(document_family=family_map.get(extension, "unknown"))


def classify_pdf(path: Path) -> DocumentClassification:
    try:
        doc = pymupdf.open(path)
    except Exception:
        return DocumentClassification(document_family="pdf", pdf_type="unknown")

    try:
        page_count = doc.page_count
        encrypted = bool(doc.needs_pass)

        if encrypted:
            return DocumentClassification(
                document_family="pdf",
                pdf_type="unknown",
                page_count=page_count,
                encrypted=True,
            )

        text_pages = 0
        image_pages = 0

        for page in doc:
            text = page.get_text("text").strip()
            if len(text) >= MIN_TEXT_CHARS_PER_PAGE:
                text_pages += 1

            if page.get_images(full=True):
                image_pages += 1

        if page_count == 0:
            pdf_type = "unknown"
        elif text_pages == 0:
            pdf_type = "scanned"
        elif text_pages == page_count:
            pdf_type = "digital"
        else:
            pdf_type = "mixed"

        return DocumentClassification(
            document_family="pdf",
            pdf_type=pdf_type,
            page_count=page_count,
            text_pages=text_pages,
            image_pages=image_pages,
            has_text_layer=text_pages > 0,
            has_images=image_pages > 0,
            encrypted=False,
        )
    finally:
        doc.close()
