from __future__ import annotations

import pytest

from forzahelper.config import get_settings
from forzahelper.db import close_pool, healthcheck


def _database_available() -> bool:
    try:
        return healthcheck()
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _database_available(),
    reason="no database configured; see db/DB_CHANGES.md",
)


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session", autouse=True)
def _close_pool_at_end():
    yield
    close_pool()
