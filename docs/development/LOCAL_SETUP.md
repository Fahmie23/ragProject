# Local Development Setup

## Recommended environment

The project is developed inside WSL Ubuntu with Docker Desktop integration. Keep the repository inside the Linux filesystem (for example `~/ragProject`) rather than under `/mnt/c/...` for normal Python/Node development.

## Prerequisites

- WSL2 Ubuntu
- Docker Desktop with WSL integration
- Python 3.12
- Node.js/npm compatible with the locked frontend environment
- NVIDIA WSL/CUDA support when GPU inference is desired

Verify Docker inside WSL:

```bash
docker version
docker ps
```

## PostgreSQL + pgvector

Start the database from the repository root:

```bash
docker compose up -d postgres
```

The local host port may be overridden (the project has used `5433` when host `5432` was occupied), while the Compose-internal service remains PostgreSQL.

## Backend

```bash
cd ~/ragProject/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

Do not commit `.env` or API keys.

Useful checks:

```text
GET http://127.0.0.1:8000/health
GET http://127.0.0.1:8000/api/system/database
GET http://127.0.0.1:8000/api/system/embeddings
GET http://127.0.0.1:8000/api/system/reranker
GET http://127.0.0.1:8000/api/system/generation
```

## Frontend

```bash
cd ~/ragProject/frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## Normal daily workflow

Terminal 1:

```bash
cd ~/ragProject
docker compose up -d postgres
```

Terminal 2:

```bash
cd ~/ragProject/backend
source .venv/bin/activate
uvicorn app.main:app --reload
```

Terminal 3:

```bash
cd ~/ragProject/frontend
npm run dev
```

## Verification

Backend regression:

```bash
cd ~/ragProject/backend
python -m pytest -q
```

Frontend production build:

```bash
cd ~/ragProject/frontend
npm run build
```

Full project verification scripts are available under `backend/scripts/` for Stage 12/13 and frozen evaluation reproduction.

## GPU checks

```bash
nvidia-smi
python -c "import torch; print(torch.cuda.is_available())"
python -c "import torch; print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU only')"
```

If `nvidia-smi` works but PyTorch reports no CUDA device, install the appropriate CUDA-enabled PyTorch build in the backend environment.

## Shutdown

```bash
docker compose down
```

Avoid `docker compose down -v` unless you intend to delete persistent data.
