from __future__ import annotations

from functools import lru_cache
from typing import Iterable

from app.config import settings
from app.services.embeddings import EmbeddingDeviceError, _torch_runtime, resolve_embedding_device


class RerankerDeviceError(RuntimeError):
    """Raised when an explicitly requested reranker device cannot be used."""

    def __init__(self, requested_device: str, message: str):
        self.requested_device = requested_device
        super().__init__(message)


class RerankerCompatibilityError(ValueError):
    """Raised when a query/passage pair would be silently truncated."""

    def __init__(self, violations: list[dict[str, int | str]]):
        self.violations = violations
        preview = ", ".join(
            f"candidate {item['index']}={item['token_count']} tokens"
            for item in violations[:5]
        )
        super().__init__(f"Reranker input exceeds configured max sequence length: {preview}")


def resolve_reranker_device(device: str | None = None) -> tuple[str, str]:
    """Use the same explicit CPU/CUDA semantics as Stage 6 embeddings."""

    requested = (device or settings.reranker_device or "auto").strip().lower()
    try:
        return resolve_embedding_device(requested)
    except EmbeddingDeviceError as exc:
        message = str(exc).replace("embeddings", "reranking").replace("embedding", "reranker")
        raise RerankerDeviceError(exc.requested_device, message) from exc


def reranker_runtime_status() -> dict[str, object]:
    runtime = _torch_runtime()
    try:
        requested, resolved = resolve_reranker_device(settings.reranker_device)
        resolution_error = None
    except RerankerDeviceError as exc:
        requested = exc.requested_device
        resolved = None
        resolution_error = str(exc)
    return {
        "reranker_model": settings.reranker_model,
        "configured_device": requested,
        "resolved_device": resolved,
        "reranker_batch_size": settings.reranker_batch_size,
        "reranker_max_length": settings.reranker_max_length,
        **runtime,
        "resolution_error": resolution_error,
    }


@lru_cache(maxsize=4)
def _load_reranker(model_name: str, device: str, max_length: int):
    try:
        from sentence_transformers import CrossEncoder
    except ImportError as exc:  # pragma: no cover - runtime dependency
        raise RuntimeError(
            "sentence-transformers is not installed. Run `pip install -r requirements.txt`."
        ) from exc
    return CrossEncoder(model_name, device=device, max_length=max_length)


def _to_float_scores(values) -> list[float]:
    raw = values.tolist() if hasattr(values, "tolist") else values
    scores: list[float] = []
    for value in raw:
        if isinstance(value, (list, tuple)):
            if len(value) != 1:
                raise ValueError("Reranker returned an unexpected multi-label score.")
            value = value[0]
        scores.append(float(value))
    return scores



class Reranker:
    """Lazy cached cross-encoder wrapper for Stage 8."""

    def __init__(
        self,
        model_name: str | None = None,
        *,
        device: str | None = None,
        batch_size: int | None = None,
        max_length: int | None = None,
    ) -> None:
        self.model_name = model_name or settings.reranker_model
        self.requested_device, self.device = resolve_reranker_device(device)
        self.batch_size = batch_size or settings.reranker_batch_size
        self.max_length = max_length or settings.reranker_max_length
        if self.batch_size < 1:
            raise ValueError("Reranker batch size must be at least 1.")
        if self.max_length < 8:
            raise ValueError("Reranker max length must be at least 8 tokens.")

    @property
    def model(self):
        return _load_reranker(self.model_name, self.device, self.max_length)

    def inspect_pairs(self, query: str, passages: Iterable[str]) -> dict[str, object]:
        clean_query = query.strip()
        if not clean_query:
            raise ValueError("Reranker query cannot be empty.")
        clean_passages = [passage.strip() for passage in passages]
        if any(not passage for passage in clean_passages):
            raise ValueError("Reranker cannot score an empty passage.")

        tokenizer = getattr(self.model, "tokenizer", None)
        if tokenizer is None:
            return {"token_counts": [], "max_length": self.max_length, "violations": []}

        counts: list[int] = []
        violations: list[dict[str, int | str]] = []
        for index, passage in enumerate(clean_passages):
            token_ids = tokenizer.encode(
                clean_query,
                passage,
                add_special_tokens=True,
                truncation=False,
            )
            token_count = len(token_ids)
            counts.append(token_count)
            if token_count > self.max_length:
                violations.append(
                    {
                        "index": index,
                        "token_count": token_count,
                        "max_length": self.max_length,
                    }
                )
        return {
            "token_counts": counts,
            "max_length": self.max_length,
            "violations": violations,
        }

    def score(self, query: str, passages: Iterable[str]) -> list[float]:
        clean_query = query.strip()
        clean_passages = [passage.strip() for passage in passages]
        if not clean_passages:
            return []
        inspection = self.inspect_pairs(clean_query, clean_passages)
        violations = list(inspection["violations"])
        if violations:
            raise RerankerCompatibilityError(violations)

        pairs = [(clean_query, passage) for passage in clean_passages]
        # CrossEncoder.predict() returns the model's configured relevance score.
        # Depending on the sentence-transformers/model configuration, a default
        # activation may already be applied. Treat this value as an opaque,
        # uncalibrated ranking score and never apply a second sigmoid here.
        values = self.model.predict(
            pairs,
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        scores = _to_float_scores(values)
        if len(scores) != len(clean_passages):
            raise ValueError("Reranker returned a score count that does not match the candidate count.")
        return scores
