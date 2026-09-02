# Stage 6 — BGE-M3 Dense Embeddings and pgvector

## Purpose

Stage 6 converts the frozen Stage 5 semantic chunks into dense vectors and stores them in PostgreSQL/pgvector. The default model is `BAAI/bge-m3`. Stage 5 remains model-independent; Stage 6 owns exact tokenizer validation and device selection.

## CPU and GPU support

One code path supports both CPU and NVIDIA CUDA GPUs.

`EMBEDDING_DEVICE` accepts:

- `auto` — use CUDA when PyTorch can access it, otherwise use CPU.
- `cpu` — force CPU even when a GPU exists.
- `cuda` — require the default CUDA GPU. If CUDA is unavailable, the request fails clearly and does not silently use CPU.
- `cuda:0`, `cuda:1`, ... — require a specific CUDA device index.

`gpu` is accepted as a convenience alias for `cuda`.

Recommended local configuration:

```env
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DEVICE=auto
EMBEDDING_BATCH_SIZE=8
```

The default batch size is conservative because BGE-M3 is substantially larger than the earlier BGE-small baseline. Increase it only after measuring RAM/VRAM headroom.

## Runtime verification

Before generating embeddings:

```bash
curl http://localhost:8000/api/system/embeddings
```

Typical GPU-capable output:

```json
{
  "embedding_model": "BAAI/bge-m3",
  "configured_device": "auto",
  "resolved_device": "cuda",
  "embedding_batch_size": 8,
  "torch_available": true,
  "cuda_available": true,
  "cuda_device_count": 1,
  "cuda_devices": [{"index": 0, "name": "..."}],
  "resolution_error": null
}
```

A CPU-only machine with `auto` resolves to `cpu`.


## Frontend Index workflow

The document workbench now exposes a dedicated **Index** tab after Stage 5. The browser is a control and monitoring surface only; embedding inference remains in FastAPI.

The Index tab can:

- read `/api/system/embeddings` and show the resolved CPU/CUDA runtime;
- choose `auto`, `cpu`, `cuda`, or a specific CUDA device for a run;
- set the embedding batch size;
- run an exact-tokenizer preflight without writing vectors;
- generate/reuse embeddings through `POST /api/documents/{document_id}/embeddings`;
- show stored chunk/vector counts and embedding dimension;
- delete the current model's vectors through the existing DELETE endpoint.

The generation request is intentionally synchronous for the current small benchmark. The frontend shows an indeterminate real-operation state rather than inventing a percentage. A background job queue/progress API should only be added when document scale makes synchronous indexing materially inconvenient.

## Exact-tokenizer preflight API

The frontend uses:

```text
POST /api/documents/{document_id}/embeddings/validate
```

with the same model/device/batch options used for generation. The response reports the model sequence limit, the exact token count of the longest chunk, and any violating chunk IDs/indexes. The endpoint does **not** write embeddings. Generation still performs the same validation again as a hard safety guard.

## Generate embeddings

The device can be selected globally through `.env` or overridden per request:

```json
{
  "embedding_model": "BAAI/bge-m3",
  "embedding_device": "auto",
  "batch_size": 8,
  "force": false
}
```

The response returns both `requested_device` and `resolved_device` so runs are auditable.

Examples:

```json
{"embedding_device": "cpu", "force": false}
```

```json
{"embedding_device": "cuda", "batch_size": 8, "force": false}
```

The stored embedding metadata also records the concrete device used to generate each vector. Device is not part of embedding identity: CPU and CUDA runs for the same model are intended to create the same semantic vector representation, so changing device alone does not require a second embedding set.

## Dense retrieval

`POST /api/retrieval/dense` accepts the same optional `embedding_device` override for query-vector generation. Retrieval responses include the requested and resolved device.

```json
{
  "document_id": "<document-id>",
  "query": "What conditions apply to delayed verification?",
  "top_k": 5,
  "embedding_model": "BAAI/bge-m3",
  "embedding_device": "auto"
}
```

pgvector similarity search itself remains in PostgreSQL and does not require the embedding GPU. The accelerator is used by the neural embedding model for chunk/query encoding.

## Exact tokenizer guard

Before encoding Stage 5 chunks, Stage 6 uses the selected model's actual tokenizer and `max_seq_length`. Any overlong input fails with `embedding_input_too_long`; content is never knowingly silently truncated.

This contract remains active even though BGE-M3 has a much larger context window than the original BGE-M3 baseline.

## CUDA setup notes for WSL

From WSL:

```bash
nvidia-smi
python -c "import torch; print(torch.cuda.is_available())"
python -c "import torch; print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU only')"
```

If `nvidia-smi` works but `torch.cuda.is_available()` is `False`, install a CUDA-enabled PyTorch build appropriate for the machine. Do not change PostgreSQL/pgvector: only the FastAPI embedding process needs CUDA.

## Failure policy

- `auto`: CUDA if available, CPU otherwise.
- explicit `cpu`: always CPU.
- explicit `cuda`/`cuda:N`: fail with `embedding_device_unavailable` if that GPU cannot be used.
- CUDA out-of-memory is not silently converted to CPU. Reduce `EMBEDDING_BATCH_SIZE` or explicitly select CPU so execution behavior remains visible and reproducible.

## Current Stage 6 baseline

1. BGE-M3 dense embeddings.
2. L2-normalized vectors.
3. PostgreSQL + pgvector persistence.
4. Exact cosine retrieval baseline.
5. No HNSW yet.
6. No sparse/hybrid retrieval yet.
7. No reranker yet.

Those are later evaluation-driven stages.
