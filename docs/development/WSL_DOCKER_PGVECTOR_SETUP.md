# WSL + Docker Desktop + PostgreSQL/pgvector Development Setup

## Purpose

This document explains how to run the RAG Workbench project using:

- Windows 11
- WSL2 with Ubuntu
- Docker Desktop
- PostgreSQL + pgvector in Docker
- FastAPI backend inside WSL
- React/Vite frontend inside WSL

The intended local architecture is:

```text
Windows 11
│
├── Docker Desktop
│   └── PostgreSQL + pgvector container
│
└── WSL2 Ubuntu
    ├── FastAPI backend
    └── React/Vite frontend
```

The PostgreSQL database runs inside Docker Desktop, while the application code runs directly inside WSL.

---

# 1. Prerequisites

Before starting, make sure the following are installed:

## Windows

- WSL2
- Ubuntu
- Docker Desktop
- Visual Studio Code
- VS Code WSL extension

## Inside WSL

- Python 3
- `python3-venv`
- Node.js
- npm
- Git
- unzip

Verify the main tools:

```bash
python3 --version
node --version
npm --version
git --version
docker --version
docker compose version
```

---

# 2. Configure Docker Desktop for WSL

Open:

```text
Docker Desktop
→ Settings
→ General
```

Make sure Docker Desktop is using the WSL2 engine.

Then open:

```text
Docker Desktop
→ Settings
→ Resources
→ WSL Integration
```

Enable your Ubuntu distribution.

Example:

```text
Enable integration with my default WSL distro    ✓
Ubuntu                                             ✓
```

Apply the changes and restart Docker Desktop if required.

---

# 3. Verify Docker from WSL

Open Ubuntu:

```powershell
wsl -d Ubuntu
```

Inside WSL, run:

```bash
docker --version
docker compose version
docker ps
```

Expected result:

```text
Docker version ...
Docker Compose version ...
CONTAINER ID   IMAGE   ...
```

If `docker ps` succeeds without `sudo`, Docker Desktop and WSL are connected correctly.

> Do not start a second Docker daemon inside Ubuntu when using Docker Desktop.

Avoid:

```bash
sudo service docker start
```

when Docker Desktop WSL integration is being used.

---

# 4. Store the Project Inside WSL

For development, keep the project inside the WSL filesystem.

Recommended:

```text
~/ragProject
```

Avoid using:

```text
/mnt/c/Users/...
```

for the active development repository whenever possible.

Example:

```bash
cd ~
mkdir -p ragProject
cd ragProject
```

If the project ZIP is in Windows Downloads:

```bash
cp /mnt/c/Users/<WINDOWS_USERNAME>/Downloads/rag_document_pipeline_rag_workbench_pgvector_v1.zip ~/
```

Extract it:

```bash
cd ~
unzip rag_document_pipeline_rag_workbench_pgvector_v1.zip
```

Enter the project directory.

The root should contain approximately:

```text
README.md
backend/
frontend/
docs/
docker-compose.yml
```

---

# 5. Start PostgreSQL + pgvector

From the project root:

```bash
docker compose up -d postgres
```

`-d` means Docker runs the service in the background.

Check the service:

```bash
docker compose ps
```

Expected result:

```text
NAME             IMAGE                    STATUS
rag-postgres     pgvector/pgvector:pg16   Up (healthy)
```

If the status is still starting, wait a few seconds and run:

```bash
docker compose ps
```

again.

To inspect logs:

```bash
docker compose logs postgres
```

To follow logs continuously:

```bash
docker compose logs -f postgres
```

Press:

```text
Ctrl+C
```

to stop viewing logs.

This does not stop PostgreSQL.

---

# 6. Verify PostgreSQL Manually

Open a PostgreSQL shell:

```bash
docker compose exec postgres psql -U rag -d rag_workbench
```

You should see:

```text
rag_workbench=#
```

Check PostgreSQL:

```sql
SELECT version();
```

Exit:

```sql
\q
```

At this stage, the `vector` extension may not exist yet because the Alembic migration has not been executed.

---

# 7. Set Up the FastAPI Backend

Enter the backend directory:

```bash
cd backend
```

Create a Python virtual environment:

```bash
python3 -m venv .venv
```

Activate it:

```bash
source .venv/bin/activate
```

The terminal should now look similar to:

```text
(.venv) user@machine:~/ragProject/backend$
```

Upgrade pip:

```bash
python -m pip install --upgrade pip
```

Install backend dependencies:

```bash
pip install -r requirements.txt
```

The PostgreSQL-related dependencies include:

```text
SQLAlchemy
psycopg
pgvector
alembic
```

---

# 8. Configure the Backend Environment

Inside:

```text
backend/
```

create the environment file:

```bash
cp .env.example .env
```

Open it:

```bash
nano .env
```

or:

```bash
code .env
```

Ensure the database configuration contains:

```env
DATABASE_URL=postgresql+psycopg://rag:rag@localhost:5432/rag_workbench
DATABASE_REQUIRED=true
```

## Why `localhost`?

The architecture is:

```text
FastAPI inside WSL
        ↓
localhost:5432
        ↓
Docker Desktop published port
        ↓
PostgreSQL container
```

Therefore:

```text
localhost
```

is the correct hostname.

Do not use:

```env
DATABASE_URL=postgresql+psycopg://rag:rag@postgres:5432/rag_workbench
```

unless the FastAPI backend is also running as a Docker Compose service.

---

# 9. Run Database Migrations

From:

```text
backend/
```

with the virtual environment active:

```bash
alembic upgrade head
```

The migration creates the application database schema and enables pgvector.

The main tables are:

```text
documents
chunks
chunk_embeddings
evaluation_questions
evaluation_runs
evaluation_results
```

Alembic also creates:

```text
alembic_version
```

to track the active schema version.

---

# 10. Verify pgvector

Return to the project root:

```bash
cd ..
```

Check whether the vector extension is enabled:

```bash
docker compose exec postgres \
  psql -U rag -d rag_workbench \
  -c "SELECT extname, extversion FROM pg_extension WHERE extname='vector';"
```

Expected result:

```text
 extname | extversion
---------+-----------
 vector  | ...
```

Check the created tables:

```bash
docker compose exec postgres \
  psql -U rag -d rag_workbench \
  -c "\dt"
```

Expected tables should include:

```text
alembic_version
documents
chunks
chunk_embeddings
evaluation_questions
evaluation_runs
evaluation_results
```

---

# 11. Start the FastAPI Backend

Enter the backend:

```bash
cd backend
```

Activate the virtual environment if it is not already active:

```bash
source .venv/bin/activate
```

Start FastAPI:

```bash
uvicorn app.main:app --reload
```

The backend should run at:

```text
http://127.0.0.1:8000
```

or:

```text
http://localhost:8000
```

Keep this terminal open.

---

# 12. Verify the Backend

Open another WSL terminal.

Check the general health endpoint:

```bash
curl http://localhost:8000/health
```

Then check the database endpoint:

```bash
curl http://localhost:8000/api/system/database
```

A healthy database should report conceptually:

```json
{
  "configured": true,
  "reachable": true,
  "pgvector_enabled": true,
  "schema_ready": true,
  "database": "rag_workbench",
  "counts": {
    "documents": 0,
    "chunks": 0,
    "embeddings": 0,
    "evaluation_questions": 0,
    "evaluation_runs": 0
  }
}
```

The exact counts may differ.

The important fields are:

```text
configured        true
reachable         true
pgvector_enabled  true
schema_ready      true
```

If all four are `true`, the PostgreSQL + pgvector integration is working.

---

# 13. Start the Frontend

Open another WSL terminal.

Enter the frontend:

```bash
cd ~/ragProject/frontend
```

If this is the first run:

```bash
npm install
```

Start Vite:

```bash
npm run dev
```

Vite should display something similar to:

```text
Local: http://localhost:5173/
```

Open the frontend from your Windows browser:

```text
http://localhost:5173
```

The FastAPI Swagger interface is available at:

```text
http://localhost:8000/docs
```

---

# 14. Recommended Terminal Layout

Use three WSL terminals during development.

## Terminal 1 — Backend

```bash
cd ~/ragProject/backend
source .venv/bin/activate
uvicorn app.main:app --reload
```

## Terminal 2 — Frontend

```bash
cd ~/ragProject/frontend
npm run dev
```

## Terminal 3 — Development Commands

Use this terminal for:

```bash
docker compose ps
```

```bash
curl http://localhost:8000/api/system/database
```

```bash
git status
```

```bash
pytest
```

```bash
alembic current
```

PostgreSQL does not require a dedicated terminal because it is running in Docker Desktop in detached mode.

---

# 15. One-Time Setup vs Daily Startup

The following commands normally only need to be performed once:

```bash
python3 -m venv .venv
pip install -r requirements.txt
npm install
cp .env.example .env
alembic upgrade head
```

You may need to run:

```bash
alembic upgrade head
```

again later if a new database migration is added to the project.

---

# 16. Daily Development Startup

After the initial setup, the normal development workflow is much shorter.

## Step 1 — Start Docker Desktop

Open Docker Desktop on Windows and wait until Docker is running.

## Step 2 — Open WSL

```powershell
wsl -d Ubuntu
```

## Step 3 — Start PostgreSQL

From the project root:

```bash
docker compose up -d postgres
```

Verify:

```bash
docker compose ps
```

## Step 4 — Start FastAPI

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload
```

## Step 5 — Start the Frontend

In another WSL terminal:

```bash
cd frontend
npm run dev
```

Your development URLs are then:

```text
Frontend:
http://localhost:5173

Backend:
http://localhost:8000

FastAPI Swagger:
http://localhost:8000/docs

PostgreSQL:
localhost:5432
```

---

# 17. Normal Shutdown Procedure

Stop FastAPI:

```text
Ctrl+C
```

Stop Vite:

```text
Ctrl+C
```

Optionally stop PostgreSQL:

```bash
docker compose stop postgres
```

The database data remains stored in the Docker volume.

To start PostgreSQL again:

```bash
docker compose up -d postgres
```

---

# 18. Docker Compose Data Safety

The PostgreSQL data is stored in a persistent Docker volume.

This command is generally safe:

```bash
docker compose down
```

It removes the container but preserves the named volume.

However, this command also deletes the database volume:

```bash
docker compose down -v
```

The result is:

```text
container        deleted
database volume  deleted
database data    deleted
```

Do not use:

```bash
docker compose down -v
```

unless you intentionally want to reset the entire database.

---

# 19. Troubleshooting

## Problem: `docker ps` Returns Permission Denied

When using Docker Desktop with WSL integration, this should normally work:

```bash
docker ps
```

without:

```bash
sudo
```

First check:

```bash
docker context ls
```

Then:

```bash
docker info
```

Verify Docker Desktop:

```text
Settings
→ Resources
→ WSL Integration
→ Ubuntu ✓
```

If necessary, from Windows PowerShell:

```powershell
wsl --shutdown
```

Then restart Docker Desktop and reopen WSL.

Avoid installing or starting a separate Docker daemon inside Ubuntu unless you intentionally want a completely separate Docker installation.

---

## Problem: PostgreSQL Container Is Not Healthy

Check:

```bash
docker compose ps
```

Then inspect logs:

```bash
docker compose logs postgres
```

Common causes include:

- port `5432` already in use
- corrupted/old Docker volume
- Docker Desktop not fully started
- incorrect Compose configuration

---

## Problem: FastAPI Cannot Connect to PostgreSQL

Check that PostgreSQL is running:

```bash
docker compose ps
```

Check the connection string:

```env
DATABASE_URL=postgresql+psycopg://rag:rag@localhost:5432/rag_workbench
```

Check the database directly:

```bash
docker compose exec postgres psql -U rag -d rag_workbench
```

Check the backend status:

```bash
curl http://localhost:8000/api/system/database
```

---

## Problem: `alembic upgrade head` Fails

Make sure:

1. PostgreSQL is running.
2. The virtual environment is activated.
3. Backend dependencies are installed.
4. `DATABASE_URL` is correct.
5. You are running the command from `backend/`.

Check:

```bash
pwd
```

Expected:

```text
.../backend
```

Then:

```bash
alembic current
alembic heads
alembic upgrade head
```

---

## Problem: Port 5432 Is Already Used

Check Windows or WSL for another PostgreSQL instance.

Inside WSL:

```bash
ss -ltnp | grep 5432
```

If another PostgreSQL service is installed inside WSL, it may conflict with Docker Desktop.

For this project, the recommended setup is:

```text
Docker Desktop PostgreSQL
```

rather than:

```text
Docker PostgreSQL
+
native WSL PostgreSQL
```

---

## Problem: Frontend Cannot Reach Backend

First verify FastAPI:

```bash
curl http://localhost:8000/health
```

Then open:

```text
http://localhost:8000/docs
```

If FastAPI works but the frontend does not, inspect the frontend API base URL configuration.

---

# 20. Development Architecture

Once everything is running:

```text
                    WINDOWS 11
                       │
                Docker Desktop
                       │
               PostgreSQL + pgvector
                       │
                    :5432
                       │
                       ▼
                    WSL2 Ubuntu
                       │
            ┌──────────┴──────────┐
            │                     │
         FastAPI                Vite
          :8000                 :5173
            │                     │
            └──────────┬──────────┘
                       │
                 Windows Browser
```

The application pipeline is:

```text
Browser
   ↓
React
   ↓
FastAPI
   ↓
PDF Pipeline
   ↓
Stage 3 Extraction
   ↓
Stage 4 Canonical Structure
   ↓
Stage 5 Semantic Chunking
   ├────────→ JSON artifact
   │
   └────────→ PostgreSQL chunks
                    ↓
              Stage 6 Embeddings
                    ↓
                 pgvector
                    ↓
                Retrieval
                    ↓
                   RAG
```

---

# 21. Initial Verification Checklist

Before moving to Stage 6 embeddings, confirm the following:

- [ ] Docker Desktop is running.
- [ ] WSL integration is enabled.
- [ ] `docker ps` works inside WSL.
- [ ] `docker compose up -d postgres` succeeds.
- [ ] PostgreSQL reports `healthy`.
- [ ] Backend virtual environment is active.
- [ ] Backend dependencies are installed.
- [ ] `.env` contains the correct `DATABASE_URL`.
- [ ] `alembic upgrade head` succeeds.
- [ ] pgvector extension exists.
- [ ] Database tables exist.
- [ ] FastAPI starts successfully.
- [ ] `GET /health` succeeds.
- [ ] `GET /api/system/database` reports:
  - `reachable = true`
  - `pgvector_enabled = true`
  - `schema_ready = true`
- [ ] Frontend starts successfully.
- [ ] The browser can open `http://localhost:5173`.
- [ ] The browser can open `http://localhost:8000/docs`.

After these checks pass, run one document through the existing pipeline and confirm that PostgreSQL receives the expected `documents` and `chunks` rows before generating embeddings.

## Stage 6 CPU/GPU check

Stage 6 supports both CPU and NVIDIA CUDA through the same FastAPI process. Recommended configuration:

```env
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DEVICE=auto
EMBEDDING_BATCH_SIZE=8
```

Check the resolved runtime device:

```bash
curl http://localhost:8000/api/system/embeddings
```

For GPU use from WSL, these should succeed:

```bash
nvidia-smi
python -c "import torch; print(torch.cuda.is_available())"
```

Use `EMBEDDING_DEVICE=cpu` to force CPU or `EMBEDDING_DEVICE=cuda` to require GPU. Explicit CUDA requests do not silently fall back to CPU.

---

# 22. Useful Commands Reference

## Start database

```bash
docker compose up -d postgres
```

## Database status

```bash
docker compose ps
```

## Database logs

```bash
docker compose logs -f postgres
```

## PostgreSQL shell

```bash
docker compose exec postgres psql -U rag -d rag_workbench
```

## Run migrations

```bash
cd backend
source .venv/bin/activate
alembic upgrade head
```

## Start backend

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload
```

## Start frontend

```bash
cd frontend
npm run dev
```

## Check API health

```bash
curl http://localhost:8000/health
```

## Check database health

```bash
curl http://localhost:8000/api/system/database
```

## Stop PostgreSQL

```bash
docker compose stop postgres
```

## Stop and remove containers

```bash
docker compose down
```

## Never use casually

```bash
docker compose down -v
```

because it deletes the PostgreSQL data volume.
