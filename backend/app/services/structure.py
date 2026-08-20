from pathlib import Path

from app.schemas import DocumentExtraction, DocumentRecord, StructuredDocument
from app.services.canonical import build_canonical_document
from app.services.layout import analyze_pdf_layout


class UnsupportedStructureError(ValueError):
    pass


def reconstruct_document(
    path: Path,
    record: DocumentRecord,
    extraction: DocumentExtraction,
) -> tuple[dict, StructuredDocument]:
    if record.validation_status != "valid":
        raise ValueError("Document must pass Stage 2 validation before structure reconstruction.")

    if record.extraction_status != "completed":
        raise ValueError("Stage 3 extraction must complete before Stage 4 structure reconstruction.")

    if record.classification.document_family != "pdf":
        raise UnsupportedStructureError(
            f"Stage 4 currently implements PDF layout analysis first. "
            f"Detected family: {record.classification.document_family}."
        )

    layout_artifact = analyze_pdf_layout(path)
    structure = build_canonical_document(
        record=record,
        extraction=extraction,
        layout_artifact=layout_artifact,
    )
    return layout_artifact, structure
