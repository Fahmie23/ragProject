from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.session import database_probe
from app.routers.documents import router as documents_router
from app.routers.system import router as system_router
from app.routers.retrieval import router as retrieval_router
from app.routers.generation import router as generation_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.database_url and settings.database_required:
        probe = database_probe()
        if not probe.get("reachable"):
            raise RuntimeError(f"Required PostgreSQL database is unavailable: {probe.get('error', 'unknown error')}")
        if not probe.get("pgvector_enabled"):
            raise RuntimeError("Required PostgreSQL database is missing the pgvector extension. Run `alembic upgrade head`.")
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_router)
app.include_router(system_router)
app.include_router(retrieval_router)
app.include_router(generation_router)


@app.get("/health")
def health() -> dict[str, object]:
    probe = database_probe()
    status = "ok"
    if settings.database_required and not probe.get("reachable"):
        status = "degraded"
    return {"status": status, "database": probe}
