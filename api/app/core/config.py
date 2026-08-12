"""Application settings loaded from environment."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve `.env` relative to the `api/` project root, NOT the current
# working directory. Without this, `python -m uvicorn` or `alembic` run
# from a different cwd (Docker CMD without WORKDIR, k8s, systemd) would
# silently fall back to the in-code defaults — which means the app
# appears to start but is missing LLM_API_KEY, WEB_BASE_URL, etc.
#
# Path math: config.py lives at `api/app/core/config.py`, so
# .parent → `api/app/core/`, .parent → `api/app/`, .parent → `api/`.
_API_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_API_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    web_base_url: str = "http://localhost:5173"

    postgres_host: str = "localhost"
    postgres_port: int = 5433
    postgres_db: str = "chatapp"
    postgres_user: str = "postgres"
    postgres_password: str = "postgreswsl"

    # ---------- User / auth ----------
    max_root_users: int = 4
    root_username_min_len: int = 3
    root_password_min_len: int = 8
    session_ttl_seconds: int = 60 * 60 * 24 * 7  # 7 days
    session_cookie_name: str = "chatapp_session"
    session_cookie_secure: bool = False

    # ---------- Prompts ----------
    prompts_file: str = "app/core/prompts.yml"
    prompts_reload: bool = False

    # ---------- Optional second endpoints (OpenAI / Anthropic / Ollama) ----------
    openai_api_key: str = ""
    openai_base_url: str = ""
    anthropic_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"

    # ---------- Primary LLM endpoint (OpenAI-compatible) ----------
    llm_api_base: str = "https://api.minimax.chat/v1"
    llm_api_key: str = ""
    llm_model: str = "MiniMax-M3"

    openai_default_model: str = "gpt-4o-mini"
    anthropic_default_model: str = "claude-3-5-sonnet-latest"
    ollama_default_model: str = "llama3.2"

    # ---------- Database URL injection (Railway / Heroku / PaaS) ----------
    # When set (e.g. by Railway's Postgres plugin), this overrides the
    # derived `postgres_*` URL. The value may be either a libpq URL
    # (`postgresql://...`) or the SQLAlchemy form (`postgresql+asyncpg://...`).
    database_url_override: str | None = Field(
        default=None,
        validation_alias="DATABASE_URL",
    )

    @property
    def database_url(self) -> str:
        raw = self.database_url_override or (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
        # Normalize to the SQLAlchemy asyncpg driver form.
        if raw.startswith("postgresql://"):
            return "postgresql+asyncpg://" + raw[len("postgresql://") :]
        if raw.startswith("postgres://"):
            return "postgresql+asyncpg://" + raw[len("postgres://") :]
        return raw


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
