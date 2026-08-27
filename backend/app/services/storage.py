import json
from pathlib import Path

from fastapi import UploadFile

from app.config import settings
from app.schemas import ChunkingArtifact, CorrectionArtifact, DocumentExtraction, DocumentRecord, ResolvedStructureArtifact, StructuredDocument


CHUNK_SIZE = 1024 * 1024


async def save_upload_and_hash(upload: UploadFile, destination: Path, max_bytes: int) -> tuple[int, str]:
    import hashlib

    sha256 = hashlib.sha256()
    total = 0

    with destination.open("wb") as f:
        while chunk := await upload.read(CHUNK_SIZE):
            total += len(chunk)
            if total > max_bytes:
                f.close()
                destination.unlink(missing_ok=True)
                raise ValueError(f"File exceeds {settings.max_upload_mb} MB upload limit.")
            sha256.update(chunk)
            f.write(chunk)

    return total, sha256.hexdigest()


def _atomic_write_json(path: Path, payload: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def write_metadata(record: DocumentRecord) -> None:
    path = settings.metadata_dir / f"{record.document_id}.json"
    _atomic_write_json(path, record.model_dump(mode="json"))


def read_metadata(document_id: str) -> DocumentRecord | None:
    path = settings.metadata_dir / f"{document_id}.json"
    if not path.exists():
        return None
    return DocumentRecord.model_validate_json(path.read_text(encoding="utf-8"))


def list_metadata() -> list[DocumentRecord]:
    records: list[DocumentRecord] = []
    for path in sorted(settings.metadata_dir.glob("*.json")):
        try:
            records.append(DocumentRecord.model_validate_json(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return sorted(records, key=lambda r: r.ingested_at, reverse=True)


def get_raw_path(record: DocumentRecord) -> Path:
    return settings.raw_dir / record.stored_filename


def write_extraction(extraction: DocumentExtraction) -> None:
    path = settings.extracted_dir / f"{extraction.document_id}.json"
    _atomic_write_json(path, extraction.model_dump(mode="json"))


def read_extraction(document_id: str) -> DocumentExtraction | None:
    path = settings.extracted_dir / f"{document_id}.json"
    if not path.exists():
        return None
    return DocumentExtraction.model_validate_json(path.read_text(encoding="utf-8"))


def write_layout_artifact(document_id: str, payload: dict) -> None:
    path = settings.layout_dir / f"{document_id}.json"
    _atomic_write_json(path, payload)


def read_layout_artifact(document_id: str) -> dict | None:
    path = settings.layout_dir / f"{document_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_structure(structure: StructuredDocument) -> None:
    path = settings.structured_dir / f"{structure.document_id}.json"
    _atomic_write_json(path, structure.model_dump(mode="json"))


def read_structure(document_id: str) -> StructuredDocument | None:
    path = settings.structured_dir / f"{document_id}.json"
    if not path.exists():
        return None
    return StructuredDocument.model_validate_json(path.read_text(encoding="utf-8"))



def write_corrections(artifact: CorrectionArtifact) -> None:
    path = settings.corrections_dir / f"{artifact.document_id}.json"
    _atomic_write_json(path, artifact.model_dump(mode="json"))


def read_corrections(document_id: str) -> CorrectionArtifact | None:
    path = settings.corrections_dir / f"{document_id}.json"
    if not path.exists():
        return None
    return CorrectionArtifact.model_validate_json(path.read_text(encoding="utf-8"))


def write_resolved_structure(artifact: ResolvedStructureArtifact) -> None:
    path = settings.resolved_dir / f"{artifact.document_id}.json"
    _atomic_write_json(path, artifact.model_dump(mode="json"))


def read_resolved_structure(document_id: str) -> ResolvedStructureArtifact | None:
    path = settings.resolved_dir / f"{document_id}.json"
    if not path.exists():
        return None
    return ResolvedStructureArtifact.model_validate_json(path.read_text(encoding="utf-8"))



def write_chunking_artifact(artifact: ChunkingArtifact) -> None:
    path = settings.chunks_dir / f"{artifact.document_id}.json"
    _atomic_write_json(path, artifact.model_dump(mode="json"))


def read_chunking_artifact(document_id: str) -> ChunkingArtifact | None:
    path = settings.chunks_dir / f"{document_id}.json"
    if not path.exists():
        return None
    return ChunkingArtifact.model_validate_json(path.read_text(encoding="utf-8"))


def delete_chunking_artifact(document_id: str) -> None:
    (settings.chunks_dir / f"{document_id}.json").unlink(missing_ok=True)


def delete_correction_artifacts(document_id: str) -> None:
    (settings.corrections_dir / f"{document_id}.json").unlink(missing_ok=True)
    (settings.resolved_dir / f"{document_id}.json").unlink(missing_ok=True)
    delete_chunking_artifact(document_id)


def delete_structure_artifacts(document_id: str) -> None:
    (settings.layout_dir / f"{document_id}.json").unlink(missing_ok=True)
    (settings.structured_dir / f"{document_id}.json").unlink(missing_ok=True)
    delete_correction_artifacts(document_id)
