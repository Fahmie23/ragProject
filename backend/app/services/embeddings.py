from __future__ import annotations

from functools import lru_cache
import re
from typing import Iterable

from app.config import settings


BGE_EN_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
_CUDA_DEVICE_RE = re.compile(r"^cuda(?::(?P<index>\d+))?$")


class EmbeddingCompatibilityError(ValueError):
    """Raised when Stage 5 chunk text would be silently truncated by a model."""

    def __init__(self, violations: list[dict[str, int]]):
        self.violations = violations
        preview = ", ".join(
            f"item {item['index']}={item['token_count']} tokens"
            for item in violations[:5]
        )
        super().__init__(f"Embedding input exceeds model max sequence length: {preview}")


class EmbeddingDeviceError(RuntimeError):
    """Raised when an explicitly requested embedding device cannot be used."""

    def __init__(self, requested_device: str, message: str):
        self.requested_device = requested_device
        super().__init__(message)


def _query_text(text: str, model_name: str) -> str:
    """Apply model-specific retrieval instructions without contaminating stored chunks."""

    normalized = model_name.lower()
    if "bge-small-en" in normalized or "bge-base-en" in normalized or "bge-large-en" in normalized:
        return f"{BGE_EN_QUERY_PREFIX}{text.strip()}"
    # BGE-M3 does not use the legacy English BGE query prefix.
    return text.strip()


def _torch_runtime() -> dict[str, object]:
    """Return CUDA capability without loading the embedding model itself."""

    try:
        import torch
    except ImportError:
        return {
            "torch_available": False,
            "cuda_available": False,
            "cuda_device_count": 0,
            "cuda_devices": [],
        }

    cuda_available = bool(torch.cuda.is_available())
    count = int(torch.cuda.device_count()) if cuda_available else 0
    devices: list[dict[str, object]] = []
    if cuda_available:
        for index in range(count):
            try:
                name = str(torch.cuda.get_device_name(index))
            except Exception:
                name = f"CUDA device {index}"
            devices.append({"index": index, "name": name})
    return {
        "torch_available": True,
        "cuda_available": cuda_available,
        "cuda_device_count": count,
        "cuda_devices": devices,
    }


def _normalize_requested_device(device: str | None) -> str:
    value = (device or settings.embedding_device or "auto").strip().lower()
    if value == "gpu":
        value = "cuda"
    if value in {"auto", "cpu"} or _CUDA_DEVICE_RE.fullmatch(value):
        return value
    raise EmbeddingDeviceError(
        value,
        "Unsupported embedding device. Use 'auto', 'cpu', 'cuda', or 'cuda:<index>'.",
    )


def resolve_embedding_device(device: str | None = None) -> tuple[str, str]:
    """Resolve a configured/requested device to the concrete sentence-transformers device.

    `auto` may fall back to CPU. Explicit CUDA requests never silently fall back.
    This makes local CPU development and GPU acceleration share the same code path
    while preserving predictable production behavior.
    """

    requested = _normalize_requested_device(device)
    if requested == "cpu":
        return requested, "cpu"

    runtime = _torch_runtime()
    cuda_available = bool(runtime["cuda_available"])
    device_count = int(runtime["cuda_device_count"])

    if requested == "auto":
        return requested, "cuda" if cuda_available else "cpu"

    if not cuda_available:
        raise EmbeddingDeviceError(
            requested,
            "CUDA was requested for embeddings, but PyTorch cannot access a CUDA GPU. "
            "Use EMBEDDING_DEVICE=cpu/auto or install a CUDA-enabled PyTorch build and verify `torch.cuda.is_available()`.",
        )

    match = _CUDA_DEVICE_RE.fullmatch(requested)
    assert match is not None
    index_text = match.group("index")
    if index_text is not None:
        index = int(index_text)
        if index >= device_count:
            raise EmbeddingDeviceError(
                requested,
                f"CUDA device index {index} was requested, but only {device_count} CUDA device(s) are available.",
            )
        return requested, f"cuda:{index}"
    return requested, "cuda"


def embedding_runtime_status() -> dict[str, object]:
    runtime = _torch_runtime()
    configured = settings.embedding_device
    try:
        requested, resolved = resolve_embedding_device(configured)
        resolution_error = None
    except EmbeddingDeviceError as exc:
        requested = _normalize_requested_device(configured)
        resolved = None
        resolution_error = str(exc)
    return {
        "embedding_model": settings.embedding_model,
        "configured_device": requested,
        "resolved_device": resolved,
        "embedding_batch_size": settings.embedding_batch_size,
        **runtime,
        "resolution_error": resolution_error,
    }


@lru_cache(maxsize=4)
def _load_model(model_name: str, device: str):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - depends on runtime dependency
        raise RuntimeError(
            "sentence-transformers is not installed. Run `pip install -r requirements.txt`."
        ) from exc
    return SentenceTransformer(model_name, device=device)


def _to_float_vectors(encoded) -> list[list[float]]:
    values = encoded.tolist() if hasattr(encoded, "tolist") else encoded
    vectors = [[float(value) for value in vector] for vector in values]
    if not vectors:
        return []
    dimension = len(vectors[0])
    if dimension <= 0 or any(len(vector) != dimension for vector in vectors):
        raise ValueError("Embedding model returned inconsistent vector dimensions.")
    return vectors


class EmbeddingEncoder:
    """Lazy sentence-transformers wrapper used by Stage 6.

    The same encoder supports CPU and CUDA. `auto` prefers CUDA when PyTorch can
    actually use it and otherwise resolves to CPU. Explicit CUDA requests fail
    instead of silently changing device.
    """

    def __init__(
        self,
        model_name: str | None = None,
        *,
        device: str | None = None,
        batch_size: int | None = None,
    ) -> None:
        self.model_name = model_name or settings.embedding_model
        self.requested_device, self.device = resolve_embedding_device(device)
        self.batch_size = batch_size or settings.embedding_batch_size
        if self.batch_size < 1:
            raise ValueError("Embedding batch size must be at least 1.")

    @property
    def model(self):
        return _load_model(self.model_name, self.device)

    def inspect_documents(self, texts: Iterable[str]) -> dict[str, object]:
        """Inspect Stage 5 text with the exact embedding tokenizer without encoding vectors.

        This powers the frontend preflight check and the hard no-truncation guard used
        by embedding generation. The embedding model is loaded lazily and remains
        cached for the subsequent generation request on the same device.
        """

        cleaned = [text.strip() for text in texts]
        if any(not text for text in cleaned):
            raise ValueError("Cannot embed an empty chunk.")
        model = self.model
        tokenizer = getattr(model, "tokenizer", None)
        max_seq_length = int(getattr(model, "max_seq_length", 0) or 0)
        if tokenizer is None or max_seq_length <= 0:
            return {
                "token_counts": [],
                "max_seq_length": None,
                "violations": [],
            }

        token_counts: list[int] = []
        violations: list[dict[str, int]] = []
        for index, text in enumerate(cleaned):
            token_ids = tokenizer.encode(text, add_special_tokens=True, truncation=False)
            token_count = len(token_ids)
            token_counts.append(token_count)
            if token_count > max_seq_length:
                violations.append({
                    "index": index,
                    "token_count": token_count,
                    "max_seq_length": max_seq_length,
                })
        return {
            "token_counts": token_counts,
            "max_seq_length": max_seq_length,
            "violations": violations,
        }

    def validate_documents(self, texts: Iterable[str]) -> list[dict[str, int]]:
        """Check Stage 5 chunks with the embedding model's exact tokenizer."""

        inspection = self.inspect_documents(texts)
        return list(inspection["violations"])

    def encode_documents(self, texts: Iterable[str]) -> list[list[float]]:
        cleaned = [text.strip() for text in texts]
        if not cleaned:
            return []
        if any(not text for text in cleaned):
            raise ValueError("Cannot embed an empty chunk.")
        violations = self.validate_documents(cleaned)
        if violations:
            raise EmbeddingCompatibilityError(violations)
        encoded = self.model.encode(
            cleaned,
            batch_size=self.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return _to_float_vectors(encoded)

    def encode_query(self, query: str) -> list[float]:
        query = query.strip()
        if not query:
            raise ValueError("Retrieval query cannot be empty.")
        encoded = self.model.encode(
            [_query_text(query, self.model_name)],
            batch_size=1,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        vectors = _to_float_vectors(encoded)
        if len(vectors) != 1:
            raise ValueError("Embedding model returned an invalid query embedding batch.")
        return vectors[0]
