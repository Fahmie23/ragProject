import json
from pathlib import Path


class LayoutDependencyError(RuntimeError):
    pass


def _version(module) -> str:
    value = getattr(module, "version", None) or getattr(module, "__version__", None)
    if callable(value):
        try:
            value = value()
        except TypeError:
            pass
    return str(value or "unknown")


def _normalize_payload(payload) -> dict:
    # Current PyMuPDF4LLM JSON output is a root object with `pages`, but this
    # normalization keeps the adapter resilient to list-only page payloads.
    if isinstance(payload, list):
        return {"page_count": len(payload), "toc": [], "pages": payload}
    if not isinstance(payload, dict):
        raise ValueError("PyMuPDF4LLM returned an unsupported JSON root type.")
    if "pages" not in payload:
        raise ValueError("PyMuPDF4LLM JSON output does not contain a 'pages' collection.")
    return payload


def analyze_pdf_layout(path: Path) -> dict:
    try:
        import pymupdf4llm
    except ModuleNotFoundError as exc:
        raise LayoutDependencyError(
            "Stage 4 requires PyMuPDF4LLM. Install backend requirements with: "
            "pip install -r requirements.txt"
        ) from exc

    settings = {
        "use_layout": True,
        "use_ocr": False,
        "force_text": True,
        "embed_images": False,
        "write_images": False,
        "show_progress": False,
    }

    # Layout is enabled by default in current PyMuPDF4LLM. Calling use_layout
    # explicitly documents our intent and prevents a prior process-level toggle
    # from silently disabling it.
    if hasattr(pymupdf4llm, "use_layout"):
        pymupdf4llm.use_layout(True)

    raw_json = pymupdf4llm.to_json(
        str(path),
        use_ocr=False,
        force_text=True,
        embed_images=False,
        write_images=False,
        show_progress=False,
    )
    payload = _normalize_payload(json.loads(raw_json))

    return {
        "engine": {
            "name": "PyMuPDF4LLM Layout",
            "version": _version(pymupdf4llm),
            "settings": settings,
        },
        "result": payload,
    }
