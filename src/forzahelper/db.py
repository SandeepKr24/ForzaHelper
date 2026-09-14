"""Database access.

A single connection pool is shared by the app. Every query goes through
`fetch_all` / `fetch_one`, which accept only parameterized SQL -- callers pass
values via the params mapping, never by string formatting.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import Settings, get_settings

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None


def get_pool(settings: Settings | None = None) -> ConnectionPool:
    global _pool
    if _pool is None:
        settings = settings or get_settings()
        min_size, max_size = settings.effective_pool_sizes
        _pool = ConnectionPool(
            conninfo=settings.conninfo,
            min_size=min_size,
            max_size=max_size,
            kwargs={
                "row_factory": dict_row,
                "options": f"-c statement_timeout={settings.statement_timeout_ms}",
                "prepare_threshold": settings.prepare_threshold,
            },
            open=False,
        )
        _pool.open()
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def connection() -> Iterator[Any]:
    with get_pool().connection() as conn:
        yield conn


def fetch_all(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with connection() as conn:
        return conn.execute(sql, params or {}).fetchall()


def fetch_one(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    with connection() as conn:
        return conn.execute(sql, params or {}).fetchone()


def healthcheck() -> bool:
    """True if the database answers and the cars view is present."""
    try:
        row = fetch_one("SELECT 1 AS ok")
        return bool(row and row["ok"] == 1)
    except Exception:
        logger.exception("database healthcheck failed")
        return False
