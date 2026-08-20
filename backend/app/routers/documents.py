from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pymupdf
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response

from app.config import settings
from app.schemas import (
    CorrectionArtifact,
    DocumentExtraction,
    DocumentRecord,
    ResolvedStructureArtifact,
    SaveCorrectionsRequest,
    SaveCorrectionsResponse,
    StructuredDocument,
    UploadResponse,
)
from app.services.classification import classify_document
from app.services.corrections import InvalidCorrectionError, StaleCorrectionError, resolve_structure
from app.services.extraction import UnsupportedExtractionError, extract_document
from app.services.layout import LayoutDependencyError
from app.services.storage import (
    delete_correction_artifacts,
    delete_structure_artifacts,
    get_raw_path,
    list_metadata,
    read_corrections,
    read_extraction,
    read_layout_artifact,
    read_metadata,
    read_resolved_structure,
    read_structure,
    save_upload_and_hash,
    write_corrections,
    write_extraction,
    write_layout_artifact,
    write_metadata,
    write_resolved_structure,
    write_structure,
)
from app.services.structure import UnsupportedStructureError, reconstruct_document
from app.services.validation import validate_file


router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)) -> UploadResponse:
    document_id = str(uuid4())
    extension = Path(file.filename or "").suffix.lower()
    stored_filename = f"{document_id}{extension}"
    destination = settings.raw_dir / stored_filename

    try:
        size_bytes, sha256 = await save_upload_and_hash(
            file,
            destination,
            max_bytes=settings.max_upload_mb * 1024 * 1024,
        )
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    detected_mime, validation_errors = validate_file(
        destination,
        file.filename or stored_filename,
    )

    classification = classify_document(destination, extension)

    if classification.document_family == "pdf":
        if classification.page_count is None:
            validation_errors.append("PDF could not be opened or inspected.")
        elif classification.page_count == 0:
            validation_errors.append("PDF contains no pages.")

    if classification.encrypted:
        validation_errors.append("Encrypted/password-protected PDFs are not accepted in this stage.")

    record = DocumentRecord(
        document_id=document_id,
        original_filename=file.filename or stored_filename,
        stored_filename=stored_filename,
        extension=extension,
        detected_mime_type=detected_mime,
        size_bytes=size_bytes,
        sha256=sha256,
        validation_status="invalid" if validation_errors else "valid",
        validation_errors=validation_errors,
        classification=classification,
        ingested_at=datetime.now(timezone.utc),
    )

    write_metadata(record)
    return UploadResponse(document=record)


@router.get("", response_model=list[DocumentRecord])
def get_documents() -> list[DocumentRecord]:
    return list_metadata()


@router.get("/{document_id}", response_model=DocumentRecord)
def get_document(document_id: str) -> DocumentRecord:
    record = read_metadata(document_id)
    if not record:
        raise HTTPException(status_code=404, detail="Document not found.")
    return record


@router.get("/{document_id}/file")
def get_document_file(document_id: str):
    record = read_metadata(document_id)
    if not record:
        raise HTTPException(status_code=404, detail="Document not found.")

    path = get_raw_path(record)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Raw file not found.")

    return FileResponse(
        path,
        media_type=record.detected_mime_type or "application/octet-stream",
        headers={"Content-Disposition": "inline"},
    )


@router.post("/{document_id}/extract", response_model=DocumentExtraction)
def run_extraction(document_id: str) -> DocumentExtraction:
    record = read_metadata(document_id)
    if not record:
        raise HTTPException(status_code=404, detail="Document not found.")

    path = get_raw_path(record)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Raw file not found.")

    # A new Stage 3 result changes the input to Stage 4. Remove old Stage 4
    # artifacts before the attempt so stale structure can never be served.
    delete_structure_artifacts(document_id)
    record.structure_status = "not_started"
    record.structure_error = None
    record.structured_at = None

    try:
        extraction = extract_document(path, record)
    except UnsupportedExtractionError as exc:
        record.extraction_status = "failed"
        record.extraction_error = str(exc)
        write_metadata(record)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        record.extraction_status = "failed"
        record.extraction_error = str(exc)
        write_metadata(record)
        raise HTTPException(status_code=500, detail=f"Extraction failed: {exc}") from exc

    write_extraction(extraction)
    record.extraction_status = "completed"
    record.extraction_error = None
    record.extracted_at = extraction.extracted_at
    write_metadata(record)
    return extraction


@router.get("/{document_id}/extraction", response_model=DocumentExtraction)
def get_extraction(document_id: str) -> DocumentExtraction:
    if not read_metadata(document_id):
        raise HTTPException(status_code=404, detail="Document not found.")

    extraction = read_extraction(document_id)
    if not extraction:
        raise HTTPException(status_code=404, detail="Extraction has not been run yet.")
    return extraction


@router.post("/{document_id}/structure", response_model=StructuredDocument)
def run_structure(document_id: str) -> StructuredDocument:
    record = read_metadata(document_id)
    if not record:
        raise HTTPException(status_code=404, detail="Document not found.")

    path = get_raw_path(record)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Raw file not found.")

    extraction = read_extraction(document_id)
    if not extraction or record.extraction_status != "completed":
        raise HTTPException(status_code=400, detail="Run Stage 3 extraction successfully before Stage 4.")

    # Never leave an older Stage 4 result available while a re-run fails.
    delete_structure_artifacts(document_id)
    record.structure_status = "not_started"
    record.structure_error = None
    record.structured_at = None
    write_metadata(record)

    try:
        layout_artifact, structure = reconstruct_document(path, record, extraction)
    except (UnsupportedStructureError, LayoutDependencyError, ValueError) as exc:
        record.structure_status = "failed"
        record.structure_error = str(exc)
        write_metadata(record)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        record.structure_status = "failed"
        record.structure_error = str(exc)
        write_metadata(record)
        raise HTTPException(status_code=500, detail=f"Structure reconstruction failed: {exc}") from exc

    write_layout_artifact(document_id, layout_artifact)
    write_structure(structure)
    record.structure_status = "completed"
    record.structure_error = None
    record.structured_at = structure.structured_at
    write_metadata(record)
    return structure


@router.get("/{document_id}/structure", response_model=StructuredDocument)
def get_structure(document_id: str) -> StructuredDocument:
    if not read_metadata(document_id):
        raise HTTPException(status_code=404, detail="Document not found.")

    structure = read_structure(document_id)
    if not structure:
        raise HTTPException(status_code=404, detail="Stage 4 structure has not been built yet.")
    return structure


@router.get("/{document_id}/corrections", response_model=CorrectionArtifact)
def get_corrections(document_id: str) -> CorrectionArtifact:
    if not read_metadata(document_id):
        raise HTTPException(status_code=404, detail="Document not found.")
    artifact = read_corrections(document_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="No Stage 4.5 corrections have been saved yet.")
    return artifact


@router.get("/{document_id}/resolved-structure", response_model=ResolvedStructureArtifact)
def get_resolved_structure(document_id: str) -> ResolvedStructureArtifact:
    if not read_metadata(document_id):
        raise HTTPException(status_code=404, detail="Document not found.")
    artifact = read_resolved_structure(document_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="No resolved Stage 4.5 structure exists yet.")
    return artifact


@router.put("/{document_id}/corrections", response_model=SaveCorrectionsResponse)
def save_corrections(document_id: str, request: SaveCorrectionsRequest) -> SaveCorrectionsResponse:
    record = read_metadata(document_id)
    if not record:
        raise HTTPException(status_code=404, detail="Document not found.")

    automatic = read_structure(document_id)
    extraction = read_extraction(document_id)
    if not automatic or record.structure_status != "completed":
        raise HTTPException(status_code=400, detail="Run Stage 4 successfully before saving Stage 4.5 corrections.")
    if not extraction or record.extraction_status != "completed":
        raise HTTPException(status_code=400, detail="Stage 3 extraction is required to resolve corrected bounding boxes.")
    if automatic.structured_at != request.base_structured_at:
        raise HTTPException(
            status_code=409,
            detail="Stage 4 changed after this correction session started. Reload the document before saving corrections.",
        )

    now = datetime.now(timezone.utc)
    artifact = CorrectionArtifact(
        document_id=document_id,
        source_sha256=automatic.source_sha256,
        base_structure_schema_version=automatic.schema_version,
        base_structured_at=automatic.structured_at,
        operations=request.operations,
        updated_at=now,
    )

    try:
        resolved = resolve_structure(automatic=automatic, extraction=extraction, corrections=artifact)
    except StaleCorrectionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidCorrectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    write_corrections(artifact)
    write_resolved_structure(resolved)
    return SaveCorrectionsResponse(corrections=artifact, resolved=resolved)


@router.delete("/{document_id}/corrections", status_code=204)
def reset_corrections(document_id: str):
    if not read_metadata(document_id):
        raise HTTPException(status_code=404, detail="Document not found.")
    delete_correction_artifacts(document_id)
    return Response(status_code=204)


@router.get("/{document_id}/layout")
def get_layout(document_id: str) -> dict:
    if not read_metadata(document_id):
        raise HTTPException(status_code=404, detail="Document not found.")

    artifact = read_layout_artifact(document_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Stage 4 layout analysis has not been run yet.")
    return artifact


@router.get("/{document_id}/pages/{page_number}/preview")
def get_page_preview(
    document_id: str,
    page_number: int,
    scale: float = Query(default=1.35, ge=0.5, le=3.0),
):
    record = read_metadata(document_id)
    if not record:
        raise HTTPException(status_code=404, detail="Document not found.")
    if record.classification.document_family != "pdf":
        raise HTTPException(status_code=400, detail="Page preview is currently available for PDFs only.")

    path = get_raw_path(record)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Raw file not found.")

    doc = pymupdf.open(path)
    try:
        if page_number < 1 or page_number > doc.page_count:
            raise HTTPException(status_code=404, detail="Page not found.")

        page = doc[page_number - 1]
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        png = pixmap.tobytes("png")
    finally:
        doc.close()

    return Response(content=png, media_type="image/png")
