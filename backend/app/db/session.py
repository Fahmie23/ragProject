from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


@lru_cache(maxsize=1)
def get_engine() -> Engine | None:
    """Return the configured SQLAlchemy engine, or ``None`` when DB use is disabled.

    Keeping engine creation lazy lets the deterministic extraction test suite run
    without PostgreSQL. In normal development ``DATABASE_URL`` enables this layer.
    """

    if not settings.database_url:
        return None
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session] | None:
    engine = get_engine()
    if engine is None:
        return None
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("DATABASE_URL is not configured.")
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def database_probe() -> dict[str, object]:
    """Return a lightweight connectivity/pgvector probe without importing models."""

    engine = get_engine()
    if engine is None:
        return {
            "configured": False,
            "reachable": False,
            "pgvector_enabled": False,
            "database": None,
        }

    try:
        with engine.connect() as connection:
            database = connection.execute(text("select current_database()"))
            database_name = database.scalar_one()
            extension = connection.execute(
                text("select exists(select 1 from pg_extension where extname = 'vector')")
            ).scalar_one()
        return {
            "configured": True,
            "reachable": True,
            "pgvector_enabled": bool(extension),
            "database": database_name,
        }
    except Exception as exc:  # pragma: no cover - depends on external service
        return {
            "configured": True,
            "reachable": False,
            "pgvector_enabled": False,
            "database": None,
            "error": str(exc),
        }
