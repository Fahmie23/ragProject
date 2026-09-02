from fastapi import APIRouter

from app.db.session import database_probe


router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/database")
def database_status() -> dict[str, object]:
    probe = database_probe()
    if not probe.get("reachable") or not probe.get("pgvector_enabled"):
        return {**probe, "counts": None}

    try:
        from app.db.repository import database_counts

        counts = database_counts()
    except Exception as exc:  # tables may not be migrated yet
        return {**probe, "counts": None, "schema_ready": False, "schema_error": str(exc)}
    return {**probe, "counts": counts, "schema_ready": True}


@router.get("/embeddings")
def embedding_system_status() -> dict[str, object]:
    from app.services.embeddings import embedding_runtime_status

    return embedding_runtime_status()


@router.get("/reranker")
def reranker_system_status() -> dict[str, object]:
    from app.services.reranking import reranker_runtime_status

    return reranker_runtime_status()



@router.get("/generation")
def generation_system_status() -> dict[str, object]:
    from app.services.generation import generation_runtime_status

    return generation_runtime_status()
