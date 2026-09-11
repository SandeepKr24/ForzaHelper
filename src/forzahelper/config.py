"""Application settings.

The existing .env uses bare keys (host, port, database, user, password). Those
names collide with real OS environment variables on some platforms, so the file
is parsed directly with dotenv_values rather than being pushed into os.environ.
Real environment variables still win, under an FH_ prefix, so deployments can
override without shipping a .env.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Backend configuration."""

    db_host: str = ""
    db_port: int = 5432
    db_name: str = ""
    db_user: str = ""
    db_password: str = ""
    database_url: str = ""

    # The view created by db/02_cars_api_view.sql. Never interpolated from user
    # input -- it is a fixed identifier used to build queries.
    cars_relation: str = "public.cars_api"

    pool_min_size: int = 1
    pool_max_size: int = 5
    statement_timeout_ms: int = 10_000

    default_limit: int = 50
    max_limit: int = 200

    # "around X" -> +/- this fraction, unless the user gives an explicit range.
    default_tolerance_pct: float = 0.10
    min_tolerance_abs: float = 5.0

    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    environment: str = "development"

    # Leave llm_model empty to use the deterministic rule-based extractor.
    llm_provider: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    # Extraction returns a small JSON object, so this ceiling is generous.
    llm_max_tokens: int = 2048
    llm_timeout_s: float = 20.0

    @model_validator(mode="after")
    def _fill_from_dotenv(self) -> "Settings":
        """Back-fill unset DB fields from the bare keys in .env."""
        if self.database_url or self.db_host:
            return self

        raw = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
        mapping = {
            "db_host": ("host",),
            "db_port": ("port",),
            "db_name": ("database", "dbname"),
            "db_user": ("user", "username"),
            "db_password": ("password",),
        }
        for field, keys in mapping.items():
            for key in keys:
                value = raw.get(key)
                if value:
                    object.__setattr__(
                        self, field, int(value) if field == "db_port" else value
                    )
                    break
        return self

    @property
    def conninfo(self) -> str:
        """libpq connection string. Never logged."""
        if self.database_url:
            return self.database_url
        if not (self.db_host and self.db_name and self.db_user):
            raise RuntimeError(
                f"Database is not configured. Set FH_DATABASE_URL, or provide "
                f"host/port/database/user/password in {ENV_PATH}."
            )
        parts = {
            "host": self.db_host,
            "port": self.db_port,
            "dbname": self.db_name,
            "user": self.db_user,
            "password": self.db_password,
            "connect_timeout": 15,
        }
        return " ".join(f"{k}={v}" for k, v in parts.items() if v != "")

    model_config = {
        "env_prefix": "FH_",
        # FH_-prefixed keys are read from .env as well as the real environment,
        # so the API key can live in .env next to the database settings. A real
        # environment variable still takes precedence, for deployment.
        "env_file": ENV_PATH,
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
