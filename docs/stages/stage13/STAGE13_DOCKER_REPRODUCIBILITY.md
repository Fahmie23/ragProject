# Stage 13 — Docker & Reproducibility

## Status

Candidate until the local dependency locks, Docker image builds, clean Compose smoke, Stage 12 regression, and Stage 11 freeze guards all pass on the developer machine.

Stage 13 is infrastructure-only. It must not tune or modify the frozen retrieval, reranking, context assembly, generation, deterministic citation, or Stage 11 evaluation behavior.

## Goals

1. Pin the language/runtime toolchain used by containers.
2. Lock Python and npm dependency resolution.
3. Start PostgreSQL + pgvector, migrations, FastAPI, and the existing frontend through one Compose project.
4. Preserve Stage 3–5 filesystem artifacts on the host and PostgreSQL state in a named volume.
5. Persist Hugging Face model downloads outside application image layers.
6. Enforce service readiness before dependent services start.
7. Verify a clean stack without making Groq calls.
8. Re-run the complete Stage 12 and Stage 11 freeze gates before Stage 13 is frozen.

## Pinned container toolchain

- Python: `python:3.12.14-slim-bookworm`
- Node.js: `node:24.19.0-bookworm-slim`
- nginx: `nginx:1.31.4-alpine`
- PostgreSQL/pgvector: `pgvector/pgvector:0.8.6-pg16-bookworm`

These are exact version tags, not floating `latest` tags. Image digests are intentionally deferred; Stage 13 v1 targets reproducible project dependency resolution and major service versions rather than byte-identical multi-architecture image manifests.

## Dependency locks

The editable input files remain:

- `backend/requirements.txt`
- `backend/requirements-dev.txt`
- `frontend/package.json`

The generated lock artifacts are:

- `backend/requirements.lock.txt`
- `backend/requirements-dev.lock.txt`
- `frontend/package-lock.json`

Generate them on the target Linux/WSL development environment:

```bash
cd backend
python -m pip install -r requirements-dev.txt
python scripts/prepare_stage13_dependency_locks.py
```

The backend Dockerfile refuses to build without `requirements.lock.txt`, and the frontend Dockerfile uses `npm ci`, which refuses a missing/inconsistent `package-lock.json`.

## Compose topology

```text
postgres (pgvector)
   │ healthcheck
   ▼
migrate (alembic upgrade head)
   │ completed successfully
   ▼
backend (FastAPI)
   │ /health = ok
   ▼
frontend (nginx static Vite build)
```

Compose uses health-aware `depends_on` conditions. The backend does not start merely because PostgreSQL has a running container; PostgreSQL must be healthy and migrations must have completed successfully.

## Persistence

- PostgreSQL: named volume `rag_pgdata`
- Hugging Face model cache: named volume `rag_hf_cache`
- Stage 3–5 document artifacts: bind mount `./backend/data:/app/data`

The BGE-M3 embedding model and BGE reranker are not downloaded during image build. They remain lazy runtime dependencies and are cached persistently after first use.

## Environment contract

`docker.env.example` documents the Docker-facing variables. Real API keys remain in the shell or an uncommitted `.env` file.

The Stage 11 verified generation model is the Docker default:

```text
openai/gpt-oss-120b
```

No Groq call is required for Stage 13 verification because Stages 9–11 already verified the provider path and Stage 11 results are reproducible offline.

## Verification

After generating the lock files:

```bash
cd backend
python scripts/run_stage13_verification.py
```

This checks:

- Stage 11 production freeze
- Stage 11 held-out benchmark freeze
- offline Stage 11 final result reproduction
- Stage 13 lock/container contract
- `docker compose config`
- complete Stage 12 verification, including frontend build
- all backend tests inside the locked Docker test target

The standard verification also builds the backend `test` target from `requirements-dev.lock.txt` and runs the entire backend test suite inside Docker. This verifies that the container dependency resolution, not only the host `.venv`, is compatible.

Then run the isolated clean Docker smoke:

```bash
python scripts/run_stage13_verification.py --include-docker-smoke
```

The smoke uses a separate Compose project plus alternate host ports, creates a fresh PostgreSQL volume, runs Alembic, starts FastAPI and the frontend, verifies HTTP/database readiness, makes zero generation calls, and removes the smoke volumes afterward.

## Normal local Docker startup

From repository root:

```bash
docker compose up -d --build
```

Then:

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`

Inside Docker, the frontend uses same-origin `/api/...` requests and nginx proxies them to `backend:8000`. This avoids coupling Docker UI behavior to a host port or extra CORS origins. Non-Docker Vite development retains `http://localhost:8000` as its default API base.
- Health: `http://localhost:8000/health`

Inspect:

```bash
docker compose ps
docker compose logs -f backend
```

Stop without deleting persistent DB/model volumes:

```bash
docker compose down
```

Delete volumes only when intentionally resetting local state:

```bash
docker compose down -v
```

## Freeze gate

Stage 13 can be frozen only after all of the following pass locally:

1. lock generation
2. Stage 13 reproducibility validator
3. Stage 12 full verification
4. clean Docker smoke
5. Stage 11 production/evaluation freeze guards
6. no changes to the seven Stage 11 frozen production files

CI/CD is explicitly out of scope for Stage 13 v1.
