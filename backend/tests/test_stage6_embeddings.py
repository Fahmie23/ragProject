from __future__ import annotations

import numpy as np
import pytest

from app.services import embeddings


class FakeModel:
    def __init__(self):
        self.calls: list[tuple[list[str], dict]] = []

    def encode(self, texts, **kwargs):
        self.calls.append((list(texts), dict(kwargs)))
        return np.asarray([[1.0, 0.0, 0.0] for _ in texts], dtype=float)


def test_bge_query_uses_retrieval_instruction_without_modifying_passages(monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(embeddings, "_load_model", lambda model_name, device: fake)
    monkeypatch.setattr(embeddings, "_load_tokenizer_spec", lambda model_name: (FakeTokenizer(), 512))
    encoder = embeddings.EmbeddingEncoder("BAAI/bge-small-en-v1.5", device="cpu", batch_size=8)

    docs = encoder.encode_documents(["  clause text  "])
    query = encoder.encode_query("enhanced CDD measures")

    assert docs == [[1.0, 0.0, 0.0]]
    assert query == [1.0, 0.0, 0.0]
    assert fake.calls[0][0] == ["clause text"]
    assert fake.calls[1][0] == [
        "Represent this sentence for searching relevant passages: enhanced CDD measures"
    ]
    assert fake.calls[0][1]["normalize_embeddings"] is True
    assert fake.calls[1][1]["normalize_embeddings"] is True


def test_non_bge_query_is_not_prefixed(monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(embeddings, "_load_model", lambda model_name, device: fake)
    encoder = embeddings.EmbeddingEncoder("some/other-model", device="cpu")

    encoder.encode_query("customer due diligence")

    assert fake.calls[0][0] == ["customer due diligence"]


def test_empty_embedding_input_is_rejected(monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(embeddings, "_load_model", lambda model_name, device: fake)
    encoder = embeddings.EmbeddingEncoder("BAAI/bge-small-en-v1.5")

    with pytest.raises(ValueError, match="empty chunk"):
        encoder.encode_documents(["   "])
    with pytest.raises(ValueError, match="cannot be empty"):
        encoder.encode_query("   ")


class FakeTokenizer:
    def encode(self, text, *, add_special_tokens=True, truncation=False):
        assert add_special_tokens is True
        assert truncation is False
        # Deterministic stand-in for an exact model tokenizer.
        return [101, *range(len(text.split())), 102]


class FakeLimitedModel(FakeModel):
    def __init__(self, max_seq_length=6):
        super().__init__()
        self.max_seq_length = max_seq_length
        self.tokenizer = FakeTokenizer()


def test_embedding_documents_reject_exact_tokenizer_overflow_instead_of_truncating(monkeypatch):
    fake = FakeLimitedModel(max_seq_length=6)
    monkeypatch.setattr(embeddings, "_load_model", lambda model_name, device: fake)
    monkeypatch.setattr(embeddings, "_load_tokenizer_spec", lambda model_name: (fake.tokenizer, fake.max_seq_length))
    encoder = embeddings.EmbeddingEncoder("BAAI/bge-small-en-v1.5", device="cpu")

    with pytest.raises(embeddings.EmbeddingCompatibilityError) as exc_info:
        encoder.encode_documents(["one two", "one two three four five"])

    assert exc_info.value.violations == [
        {"index": 1, "token_count": 7, "max_seq_length": 6}
    ]
    assert fake.calls == []


def test_embedding_exact_tokenizer_validation_allows_safe_chunks(monkeypatch):
    fake = FakeLimitedModel(max_seq_length=8)
    monkeypatch.setattr(embeddings, "_load_model", lambda model_name, device: fake)
    monkeypatch.setattr(embeddings, "_load_tokenizer_spec", lambda model_name: (fake.tokenizer, fake.max_seq_length))
    encoder = embeddings.EmbeddingEncoder("BAAI/bge-small-en-v1.5", device="cpu")

    vectors = encoder.encode_documents(["one two", "three four five"])

    assert len(vectors) == 2
    assert len(fake.calls) == 1



def test_device_auto_prefers_cuda_when_available(monkeypatch):
    monkeypatch.setattr(
        embeddings,
        "_torch_runtime",
        lambda: {
            "torch_available": True,
            "cuda_available": True,
            "cuda_device_count": 1,
            "cuda_devices": [{"index": 0, "name": "Test GPU"}],
        },
    )
    requested, resolved = embeddings.resolve_embedding_device("auto")
    assert requested == "auto"
    assert resolved == "cuda"


def test_device_auto_falls_back_to_cpu_when_cuda_unavailable(monkeypatch):
    monkeypatch.setattr(
        embeddings,
        "_torch_runtime",
        lambda: {
            "torch_available": True,
            "cuda_available": False,
            "cuda_device_count": 0,
            "cuda_devices": [],
        },
    )
    requested, resolved = embeddings.resolve_embedding_device("auto")
    assert requested == "auto"
    assert resolved == "cpu"


def test_explicit_cpu_never_switches_to_cuda(monkeypatch):
    monkeypatch.setattr(
        embeddings,
        "_torch_runtime",
        lambda: {
            "torch_available": True,
            "cuda_available": True,
            "cuda_device_count": 1,
            "cuda_devices": [{"index": 0, "name": "Test GPU"}],
        },
    )
    requested, resolved = embeddings.resolve_embedding_device("cpu")
    assert requested == "cpu"
    assert resolved == "cpu"


def test_explicit_cuda_fails_instead_of_silent_cpu_fallback(monkeypatch):
    monkeypatch.setattr(
        embeddings,
        "_torch_runtime",
        lambda: {
            "torch_available": True,
            "cuda_available": False,
            "cuda_device_count": 0,
            "cuda_devices": [],
        },
    )
    with pytest.raises(embeddings.EmbeddingDeviceError, match="CUDA was requested"):
        embeddings.resolve_embedding_device("cuda")


def test_specific_cuda_index_is_validated(monkeypatch):
    monkeypatch.setattr(
        embeddings,
        "_torch_runtime",
        lambda: {
            "torch_available": True,
            "cuda_available": True,
            "cuda_device_count": 2,
            "cuda_devices": [
                {"index": 0, "name": "GPU 0"},
                {"index": 1, "name": "GPU 1"},
            ],
        },
    )
    assert embeddings.resolve_embedding_device("cuda:1") == ("cuda:1", "cuda:1")
    with pytest.raises(embeddings.EmbeddingDeviceError, match="only 2 CUDA device"):
        embeddings.resolve_embedding_device("cuda:2")


def test_gpu_alias_maps_to_cuda(monkeypatch):
    monkeypatch.setattr(
        embeddings,
        "_torch_runtime",
        lambda: {
            "torch_available": True,
            "cuda_available": True,
            "cuda_device_count": 1,
            "cuda_devices": [{"index": 0, "name": "Test GPU"}],
        },
    )
    assert embeddings.resolve_embedding_device("gpu") == ("cuda", "cuda")


def test_encoder_exposes_requested_and_resolved_device(monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(embeddings, "_load_model", lambda model_name, device: fake)
    monkeypatch.setattr(
        embeddings,
        "_torch_runtime",
        lambda: {
            "torch_available": True,
            "cuda_available": True,
            "cuda_device_count": 1,
            "cuda_devices": [{"index": 0, "name": "Test GPU"}],
        },
    )
    encoder = embeddings.EmbeddingEncoder("BAAI/bge-m3", device="auto", batch_size=4)
    assert encoder.requested_device == "auto"
    assert encoder.device == "cuda"
    assert encoder.batch_size == 4


def test_embedding_document_inspection_reports_exact_counts_and_limit(monkeypatch):
    fake = FakeLimitedModel(max_seq_length=8)
    monkeypatch.setattr(embeddings, "_load_model", lambda model_name, device: fake)
    monkeypatch.setattr(embeddings, "_load_tokenizer_spec", lambda model_name: (fake.tokenizer, fake.max_seq_length))
    encoder = embeddings.EmbeddingEncoder("BAAI/bge-m3", device="cpu")

    inspection = encoder.inspect_documents(["one two", "three four five"])

    assert inspection == {
        "token_counts": [4, 5],
        "max_seq_length": 8,
        "violations": [],
    }
    assert fake.calls == []


def test_embedding_document_inspection_reports_all_overflow_candidates(monkeypatch):
    fake = FakeLimitedModel(max_seq_length=5)
    monkeypatch.setattr(embeddings, "_load_model", lambda model_name, device: fake)
    monkeypatch.setattr(embeddings, "_load_tokenizer_spec", lambda model_name: (fake.tokenizer, fake.max_seq_length))
    encoder = embeddings.EmbeddingEncoder("BAAI/bge-m3", device="cpu")

    inspection = encoder.inspect_documents(["one two three four", "one", "one two three four five"])

    assert inspection["token_counts"] == [6, 3, 7]
    assert inspection["max_seq_length"] == 5
    assert inspection["violations"] == [
        {"index": 0, "token_count": 6, "max_seq_length": 5},
        {"index": 2, "token_count": 7, "max_seq_length": 5},
    ]


def test_embedding_compatibility_preflight_maps_longest_chunk_and_violations(monkeypatch):
    from types import SimpleNamespace
    from app.routers import documents
    from app.schemas import GenerateEmbeddingsRequest

    artifact = SimpleNamespace(
        chunks=[
            SimpleNamespace(chunk_id="c0", chunk_index=0, text="short"),
            SimpleNamespace(chunk_id="c1", chunk_index=1, text="longer text"),
        ]
    )
    monkeypatch.setattr(documents, "_validated_stage5_artifact", lambda document_id: (None, artifact))

    class FakeEncoder:
        requested_device = "auto"
        device = "cuda"

        def __init__(self, model_name, *, device=None, batch_size=None):
            assert model_name == "BAAI/bge-m3"
            assert device == "auto"
            assert batch_size == 8

        def inspect_documents(self, texts):
            assert texts == ["short", "longer text"]
            return {
                "token_counts": [3, 10],
                "max_seq_length": 8,
                "violations": [{"index": 1, "token_count": 10, "max_seq_length": 8}],
            }

    monkeypatch.setattr(embeddings, "EmbeddingEncoder", FakeEncoder)
    response = documents.validate_embedding_compatibility(
        "doc-1",
        GenerateEmbeddingsRequest(
            embedding_model="BAAI/bge-m3",
            embedding_device="auto",
            batch_size=8,
        ),
    )

    assert response.document_id == "doc-1"
    assert response.resolved_device == "cuda"
    assert response.compatible is False
    assert response.compatible_chunk_count == 1
    assert response.violation_count == 1
    assert response.max_model_token_count == 10
    assert response.longest_chunk_id == "c1"
    assert response.longest_chunk_index == 1
    assert response.violations[0].chunk_id == "c1"


def test_compatibility_preflight_does_not_load_sentence_transformer_weights(monkeypatch):
    monkeypatch.setattr(embeddings, "_load_tokenizer_spec", lambda model_name: (FakeTokenizer(), 8))
    monkeypatch.setattr(embeddings, "_load_model", lambda model_name, device: (_ for _ in ()).throw(AssertionError("full model must not load")))
    encoder = embeddings.EmbeddingEncoder("BAAI/bge-m3", device="cpu")

    inspection = encoder.inspect_documents(["one two", "three four"])

    assert inspection["token_counts"] == [4, 4]
    assert inspection["max_seq_length"] == 8
