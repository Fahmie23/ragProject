from pathlib import Path
import zipfile


ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".html", ".htm"}
EXPECTED_MIME = {
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".txt": {"text/plain"},
    ".md": {"text/plain", "text/markdown"},
    ".html": {"text/html", "text/plain"},
    ".htm": {"text/html", "text/plain"},
}


def detect_mime(path: Path) -> str | None:
    """Small deterministic signature detector for the formats this project accepts.

    It intentionally avoids trusting the browser-provided Content-Type or filename alone.
    """
    try:
        head = path.read_bytes()[:8192]
    except OSError:
        return None

    if head.startswith(b"%PDF-"):
        return "application/pdf"

    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
            if "[Content_Types].xml" in names and "word/document.xml" in names:
                return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        except (OSError, zipfile.BadZipFile):
            return None
        return "application/zip"

    if b"\x00" in head:
        return None

    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        return None

    lowered = text.lstrip().lower()
    if lowered.startswith("<!doctype html") or "<html" in lowered[:1000]:
        return "text/html"

    return "text/plain"


def validate_file(path: Path, original_filename: str) -> tuple[str | None, list[str]]:
    errors: list[str] = []
    extension = Path(original_filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        errors.append(f"Unsupported extension: {extension or '(none)'}")

    if path.stat().st_size == 0:
        errors.append("File is empty.")
        return None, errors

    detected_mime = detect_mime(path)

    if extension in EXPECTED_MIME:
        if detected_mime is None:
            errors.append("File signature/content could not be confirmed for this extension.")
        elif detected_mime not in EXPECTED_MIME[extension]:
            errors.append(
                "File signature does not match extension. "
                f"Extension={extension}, detected MIME={detected_mime}"
            )

    return detected_mime, errors
