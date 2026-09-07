# Docker and Reproducibility

## Goal

The deployment layer reproduces the frozen RAG system; it is not allowed to tune retrieval/generation behavior.

## Pinned container toolchain

```text
Python              3.12.14 (slim-bookworm)
Node.js             24.19.0 (bookworm-slim)
nginx               1.31.4-alpine
PostgreSQL/pgvector pgvector 0.8.6 + PostgreSQL 16
```

Python and npm dependency lock files are generated and consumed by container builds. The backend test target uses the locked development dependencies; the frontend build uses `npm ci`.

## Compose topology

```text
postgres (pgvector)
   │ healthcheck
   ↓
migrate (alembic upgrade head)
   │ completed
   ↓
backend (FastAPI)
   │ /health
   ↓
frontend (nginx + Vite build)
```

Services depend on health/migration completion rather than container-start order alone.

## Persistence

- PostgreSQL state: named volume `rag_pgdata`.
- Hugging Face model cache: named volume `rag_hf_cache`.
- deterministic document artifacts: bind-mounted `./backend/data:/app/data`.

Embedding/reranker models are lazy runtime dependencies and are cached outside application image layers.

## Environment

`docker.env.example` documents Docker-facing variables. Real secrets belong in the shell or an uncommitted `.env` file.

## Normal startup

From repository root:

```bash
docker compose up -d --build
```

Then:

```text
Frontend  http://localhost:5173
Backend   http://localhost:8000
Health    http://localhost:8000/health
```

The Docker frontend uses same-origin `/api/...` requests and nginx proxies to `backend:8000`.

Inspect/stop:

```bash
docker compose ps
docker compose logs -f backend
docker compose down
```

Do not use `docker compose down -v` unless intentionally deleting persistent database/model-cache volumes.

## Verification

`backend/scripts/run_stage13_verification.py` combines freeze guards, Stage 11 offline reproduction, lock/container checks, Compose config validation, Stage 12 verification and backend tests in the locked Docker target.

```bash
cd backend
python scripts/run_stage13_verification.py
python scripts/run_stage13_verification.py --include-docker-smoke
```

The clean smoke uses a separate Compose project/ports and a fresh PostgreSQL volume, then removes the smoke volumes afterward.

## GPU runtime

The final local runtime was also verified with the project's NVIDIA GPU path for BGE-M3/reranker inference. Device choice is runtime profiling/configuration; it does not redefine retrieval quality semantics.

CI/CD is intentionally outside the portfolio's frozen scope.
