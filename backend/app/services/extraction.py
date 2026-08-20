from pathlib import Path

from app.schemas import DocumentExtraction, DocumentRecord
from app.services.extractors import extract_pdf


class UnsupportedExtractionError(ValueError):
    pass


def extract_document(path: Path, record: DocumentRecord) -> DocumentExtraction:
    if record.validation_status != "valid":
        raise ValueError("Document must pass Stage 2 validation before extraction.")

    if record.classification.encrypted:
        raise ValueError("Encrypted PDFs cannot be extracted.")

    if record.classification.document_family == "pdf":
        return extract_pdf(path, record)

    raise UnsupportedExtractionError(
        f"Stage 3 currently implements PDF extraction only. "
        f"Detected family: {record.classification.document_family}."
    )
