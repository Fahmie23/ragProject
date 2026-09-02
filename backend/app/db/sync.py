from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from app.config import settings


logger = logging.getLogger(__name__)
T = TypeVar("T")


def database_enabled() -> bool:
    return bool(settings.database_url)


def run_database_write(operation: Callable[[], T]) -> T | None:
    """Run an optional persistence side effect with explicit failure semantics."""

    if not database_enabled():
        return None
    try:
        return operation()
    except Exception:
        if settings.database_required:
            raise
        logger.exception("Database persistence failed; filesystem artifact was retained.")
        return None
