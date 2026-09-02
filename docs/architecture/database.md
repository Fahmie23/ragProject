# PostgreSQL + pgvector storage architecture

## Purpose

The RAG Workbench uses PostgreSQL for durable application/retrieval metadata and pgvector for chunk embeddings. Deterministic pipeline artifacts remain files so each stage is inspectable and reproducible.

```text
PDF / Stage artifacts (filesystem)
            │
            ├── metadata JSON
            ├── extraction JSON
            ├── canonical/resolved JSON
            └── chunk JSON  ← deterministic source of truth
                              │
                              ▼
                       PostgreSQL
                       ├── documents
                       ├── chunks
                       ├── evaluation_questions
                       ├── evaluation_runs
                       └── evaluation_results
                              │
                              ▼
                          pgvector
                       └── chunk_embeddings
```

The database does **not** replace Stage 3/4/5 JSON. It provides queryable persistence for the frontend, indexing, retrieval and evaluation layers.

## Tables

### `documents`

Mirrors application-level document metadata and pipeline status. `write_metadata()` remains responsible for the JSON artifact and synchronizes this row when PostgreSQL is enabled.

### `chunks`

Stores Stage 5 retrieval chunk text and provenance metadata. Regenerating Stage 5 replaces the document's rows transactionally. Existing embeddings cascade-delete so stale vectors cannot survive a chunking change.

### `chunk_embeddings`

Stores one vector per `(chunk_id, embedding_model)`. The column is variable-dimension initially because the portfolio has not frozen an embedding model yet. Once the model is fixed, a later migration can constrain the dimension and add an HNSW/IVFFlat index appropriate to that model.

### Evaluation tables

`evaluation_questions`, `evaluation_runs`, and `evaluation_results` provide the persistence contract for the later Evaluation workspace. They are created now but are not yet wired to evaluation endpoints.

## Local setup

From repository root:

```bash
docker compose up -d postgres
```

Then configure the backend:

```bash
cd backend
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Database status:

```text
GET http://127.0.0.1:8000/api/system/database
```

A ready response reports `reachable=true`, `pgvector_enabled=true`, `schema_ready=true`, plus row counts.

## Failure policy

- With no `DATABASE_URL`, the existing deterministic file pipeline runs without DB persistence. This keeps isolated tests simple.
- With `DATABASE_URL` configured and `DATABASE_REQUIRED=false`, filesystem artifacts remain authoritative if the database is temporarily unavailable; the failure is logged.
- With `DATABASE_REQUIRED=true`, the API fails fast at startup if PostgreSQL/pgvector is unavailable. This is the recommended normal application mode.

## Migration policy

Alembic owns the relational schema. Do not add production tables with `Base.metadata.create_all()` in application startup. Schema changes should be represented as a new file under `backend/alembic/versions/` and applied with:

```bash
alembic upgrade head
```

## Embedding index intentionally deferred

No ANN index is created yet. The embedding model/dimension has not been selected, and pgvector index configuration depends on that choice. Stage 6 should:

1. select and record the embedding model;
2. generate chunk embeddings;
3. constrain/validate vector dimensions;
4. add cosine-distance retrieval;
5. create HNSW (or another justified pgvector index) after evaluating the baseline.

This avoids prematurely optimizing an embedding configuration that may still change.
