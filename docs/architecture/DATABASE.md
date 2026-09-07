# Database and Persistence

## Purpose

PostgreSQL provides durable application/retrieval metadata and experiment/evaluation persistence. pgvector stores dense chunk embeddings. Deterministic document-processing artifacts remain files so their lineage can be inspected independently of database state.

## Main tables

### `documents`

Mirrors document identity, SHA-256, validation/classification and pipeline status.

### `chunks`

Stores the Stage 5 retrieval text and provenance needed by retrieval. Regenerating Stage 5 replaces a document's live chunk rows; embeddings cascade-delete so stale vectors cannot survive a chunking change.

### `chunk_embeddings`

One vector per `(chunk_id, embedding_model)`. Embeddings are stored through pgvector. Retrieval v1 uses normalized BGE-M3 vectors and exact cosine search for the controlled corpus.

### Evaluation tables

`evaluation_questions`, `evaluation_runs`, and `evaluation_results` support persisted evaluation data/results.

### Stage 15 experiment tables

`retrieval_experiments` stores an experiment definition and baseline profile.

`retrieval_experiment_runs` stores one immutable question execution snapshot including document SHA, exact normalized config, Stage 5 fingerprint, trace version, timing, application commit and error state.

`retrieval_experiment_candidates` stores the per-run candidate union with dense, lexical, RRF and reranker ranks/scores.

Candidate `chunk_id` is deliberately **not** a foreign key to the live `chunks` table: historical experiments must survive a future Stage 5 resynchronization that deletes/recreates live chunk rows.

## Filesystem vs database

```text
Filesystem (deterministic evidence)
  metadata → extraction → layout → structure → corrections → resolved → chunks

PostgreSQL (runtime/queryable state)
  documents → chunks → embeddings
  evaluation history
  controlled experiment history
```

When provenance disagreements occur, the frozen deterministic artifact chain is the evidence source used by citation validation.

## Schema ownership

Alembic owns production relational schema changes. Application startup must not create production tables ad hoc with `Base.metadata.create_all()`.

```bash
cd backend
alembic upgrade head
```

## Database failure policy

- Without `DATABASE_URL`, deterministic file-only code paths can be used by isolated tests.
- With `DATABASE_REQUIRED=false`, temporary database failures need not invalidate already-written deterministic artifacts.
- With `DATABASE_REQUIRED=true`, startup fails when PostgreSQL/pgvector is unavailable. This is the normal application expectation.

`GET /api/system/database` exposes readiness without revealing secrets.

## Indexing choice

The portfolio corpus contains 284 frozen Stage 5 chunks, so Retrieval v1 intentionally uses exact pgvector cosine rather than claiming ANN infrastructure that is not necessary for the measured workload. HNSW/IVFFlat and persisted FTS indexes are scale optimizations for a larger corpus, not prerequisites for this benchmark.
