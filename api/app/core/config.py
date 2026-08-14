"""Application settings loaded from YAML.

The configuration file is `api/config.yml` (template at `config.example.yml`).
It is **not** auto-generated from `.env` — the YAML file is the single source
of truth for non-runtime settings.

Priority (highest first):
    1. Shell environment variables that PaaS providers inject (currently
       only `DATABASE_URL`, which Railway / Heroku set on linked services).
    2. Values in `config.yml`.

If `config.yml` is missing, the process exits with a clear error — silent
fallback to in-code defaults has caused production incidents (LLM_API_KEY
"disappearing" because the .env was missing on the server).

The public API (`settings.app_env`, `settings.database_url`, etc.) is
unchanged, so downstream callers don't need to know about the YAML loader.
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

# Resolve `.yml` relative to the `api/` project root, NOT the current working
# directory. Without this, `python -m uvicorn` or `alembic` run from a
# different cwd (Docker CMD without WORKDIR, k8s, systemd) would silently
# miss the config file.
#
# Path math: config.py lives at `api/app/core/config.py`, so
# .parent → `api/app/core/`, .parent → `api/app/`, .parent → `api/`.
_API_ROOT = Path(__file__).resolve().parent.parent.parent

_DEFAULT_CONFIG_PATH = _API_ROOT / "config.yml"

# Runtime-injected env vars that override the YAML. Keep this list narrow —
# every entry is a contract that has to keep working in Railway / Heroku.
_ENV_OVERRIDES: tuple[str, ...] = ("DATABASE_URL",)


# --------------------------------------------------------------------------- #
# Nested YAML schema (used purely for validation + IDE friendliness).
# --------------------------------------------------------------------------- #


class AppCfg(BaseModel):
    env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    web_base_url: str = "http://localhost:5173"


class PostgresCfg(BaseModel):
    host: str = "localhost"
    port: int = 5433
    database: str = "chatapp"
    user: str = "postgres"
    password: str = "postgreswsl"


class DatabaseCfg(BaseModel):
    url: str | None = None
    postgres: PostgresCfg = Field(default_factory=PostgresCfg)


class OpenlikeCfg(BaseModel):
    api_base: str = "https://api.minimax.chat/v1"
    api_key: str = ""
    models: list[str] = Field(default_factory=lambda: ["MiniMax-M3"])


class OpenAiCfg(BaseModel):
    api_key: str = ""
    base_url: str = ""
    models: list[str] = Field(default_factory=lambda: ["gpt-4o-mini"])


class AnthropicCfg(BaseModel):
    api_key: str = ""
    # Empty → official api.anthropic.com. Can point at Anthropic-compatible
    # endpoints, e.g. "https://dashscope.aliyuncs.com/apps/anthropic" for
    # Aliyun's dashscope (serves qwen models through the Claude API shape).
    base_url: str = ""
    models: list[str] = Field(default_factory=lambda: ["claude-3-5-sonnet-latest"])


class OllamaCfg(BaseModel):
    base_url: str = "http://localhost:11434"
    models: list[str] = Field(default_factory=lambda: ["llama3.2"])


class OpenAiCompatCfg(BaseModel):
    """Any OpenAI-compatible endpoint (separate slot from the official
    OpenAI provider). e.g. dashscope's OpenAI-compatible API for qwen.

    When `api_key` is empty the whole provider is hidden from the UI
    (see routes.get_models).
    """

    api_key: str = ""
    base_url: str = ""
    models: list[str] = Field(default_factory=list)


class AnthropicCompatCfg(BaseModel):
    """Any Anthropic-compatible endpoint (separate slot from the official
    Anthropic provider). e.g. dashscope's `/apps/anthropic` endpoint.

    When `api_key` is empty the whole provider is hidden from the UI.
    """

    api_key: str = ""
    base_url: str = ""
    models: list[str] = Field(default_factory=list)


class LlmCfg(BaseModel):
    openlike: OpenlikeCfg = Field(default_factory=OpenlikeCfg)
    openai: OpenAiCfg = Field(default_factory=OpenAiCfg)
    anthropic: AnthropicCfg = Field(default_factory=AnthropicCfg)
    ollama: OllamaCfg = Field(default_factory=OllamaCfg)
    openai_compat: OpenAiCompatCfg = Field(default_factory=OpenAiCompatCfg)
    anthropic_compat: AnthropicCompatCfg = Field(default_factory=AnthropicCompatCfg)


class SessionCfg(BaseModel):
    ttl_seconds: int = 60 * 60 * 24 * 7  # 7 days
    cookie_name: str = "chatapp_session"
    cookie_secure: bool = False


class AuthCfg(BaseModel):
    max_root_users: int = 4
    root_username_min_len: int = 3
    root_password_min_len: int = 8
    session: SessionCfg = Field(default_factory=SessionCfg)


class PromptsCfg(BaseModel):
    file: str = "app/core/prompts.yml"
    reload: bool = False


class GraphCfg(BaseModel):
    """Graph DB (library_coderag) connection settings used by tools."""

    # `schema` shadows BaseModel.schema(); use a distinct field name.
    schema_name: str = Field(default="library_coderag", alias="schema")
    default_project: str = ""

    model_config = {"populate_by_name": True}


class RootCfg(BaseModel):
    app: AppCfg = Field(default_factory=AppCfg)
    database: DatabaseCfg = Field(default_factory=DatabaseCfg)
    llm: LlmCfg = Field(default_factory=LlmCfg)
    auth: AuthCfg = Field(default_factory=AuthCfg)
    prompts: PromptsCfg = Field(default_factory=PromptsCfg)
    graph: GraphCfg = Field(default_factory=GraphCfg)


# --------------------------------------------------------------------------- #
# Flat settings — the legacy shape that all downstream code reads.
# --------------------------------------------------------------------------- #


class Settings(BaseSettings):
    # No `env_file=...`: configuration is loaded explicitly from YAML above.
    # We still keep BaseSettings for type coercion / validation.
    model_config = {
        "case_sensitive": False,
        "extra": "ignore",
    }

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

    # ---------- Graph DB (library_coderag schema) ----------
    graph_schema: str = "library_coderag"
    graph_default_project: str = ""

    # ---------- Primary LLM endpoint (OpenAI-compatible, default) ----------
    openlike_api_base: str = "https://api.minimax.chat/v1"
    openlike_api_key: str = ""

    # ---------- Optional second endpoints (OpenAI / Anthropic / Ollama) ----------
    openai_api_key: str = ""
    openai_base_url: str = ""
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""
    ollama_base_url: str = "http://localhost:11434"

    # ---------- Compat endpoints (separate provider slots) ----------
    openai_compat_api_key: str = ""
    openai_compat_base_url: str = ""
    anthropic_compat_api_key: str = ""
    anthropic_compat_base_url: str = ""

    # ---------- Per-provider model lists (first entry = default) ----------
    # Each provider exposes one or more model identifiers. The frontend
    # dropdown shows all of them under the matching provider label; the
    # first entry is the implicit default when the user has not picked
    # one explicitly. An empty list hides the provider from the UI.
    openlike_models: list[str] = Field(default_factory=lambda: ["MiniMax-M3"])
    openai_models: list[str] = Field(default_factory=lambda: ["gpt-4o-mini"])
    anthropic_models: list[str] = Field(default_factory=lambda: ["claude-3-5-sonnet-latest"])
    ollama_models: list[str] = Field(default_factory=lambda: ["llama3.2"])
    openai_compat_models: list[str] = Field(default_factory=list)
    anthropic_compat_models: list[str] = Field(default_factory=list)

    # ---------- Database URL override (Railway / Heroku / PaaS) ----------
    # When set (e.g. by Railway's Postgres plugin), this overrides the
    # derived `postgres_*` URL. The value may be either a libpq URL
    # (`postgresql://...`) or the SQLAlchemy form (`postgresql+asyncpg://...`).
    database_url_override: str | None = None

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


# --------------------------------------------------------------------------- #
# Loader
# --------------------------------------------------------------------------- #


def _resolve_config_path() -> Path:
    """Return the active config path (`CONFIG_PATH` env wins, else default)."""
    override = os.environ.get("CONFIG_PATH")
    if override:
        return Path(override).expanduser().resolve()
    return _DEFAULT_CONFIG_PATH


def _load_yaml() -> RootCfg:
    path = _resolve_config_path()
    if not path.exists():
        # Loud failure: the operator almost certainly wants to know about this.
        # (Compare to the previous .env loader, which silently fell back to
        # in-code defaults — that meant the app started but had no
        # LLM_API_KEY, no WEB_BASE_URL, etc., and the bug only surfaced
        # at the first LLM call.)
        sys.stderr.write(
            f"config error: {path} not found.\n"
            f"  Copy {path.parent / 'config.example.yml'} to {path} and edit it.\n"
            f"  Or set CONFIG_PATH=/path/to/config.yml.\n"
        )
        raise SystemExit(2)

    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        sys.stderr.write(
            f"config error: {path} must contain a YAML mapping at the top level.\n"
        )
        raise SystemExit(2)

    return RootCfg.model_validate(raw)


def _flatten(cfg: RootCfg) -> dict[str, object]:
    """Project the nested YAML schema onto the flat Settings field names."""
    return {
        "app_env": cfg.app.env,
        "api_host": cfg.app.host,
        "api_port": cfg.app.port,
        "web_base_url": cfg.app.web_base_url,
        "postgres_host": cfg.database.postgres.host,
        "postgres_port": cfg.database.postgres.port,
        "postgres_db": cfg.database.postgres.database,
        "postgres_user": cfg.database.postgres.user,
        "postgres_password": cfg.database.postgres.password,
        "max_root_users": cfg.auth.max_root_users,
        "root_username_min_len": cfg.auth.root_username_min_len,
        "root_password_min_len": cfg.auth.root_password_min_len,
        "session_ttl_seconds": cfg.auth.session.ttl_seconds,
        "session_cookie_name": cfg.auth.session.cookie_name,
        "session_cookie_secure": cfg.auth.session.cookie_secure,
        "prompts_file": cfg.prompts.file,
        "prompts_reload": cfg.prompts.reload,
        "graph_schema": cfg.graph.schema_name,
        "graph_default_project": cfg.graph.default_project,
        "openai_api_key": cfg.llm.openai.api_key,
        "openai_base_url": cfg.llm.openai.base_url,
        "anthropic_api_key": cfg.llm.anthropic.api_key,
        "anthropic_base_url": cfg.llm.anthropic.base_url,
        "ollama_base_url": cfg.llm.ollama.base_url,
        "openlike_api_base": cfg.llm.openlike.api_base,
        "openlike_api_key": cfg.llm.openlike.api_key,
        "openai_compat_api_key": cfg.llm.openai_compat.api_key,
        "openai_compat_base_url": cfg.llm.openai_compat.base_url,
        "anthropic_compat_api_key": cfg.llm.anthropic_compat.api_key,
        "anthropic_compat_base_url": cfg.llm.anthropic_compat.base_url,
        "openlike_models": list(cfg.llm.openlike.models),
        "openai_models": list(cfg.llm.openai.models),
        "anthropic_models": list(cfg.llm.anthropic.models),
        "ollama_models": list(cfg.llm.ollama.models),
        "openai_compat_models": list(cfg.llm.openai_compat.models),
        "anthropic_compat_models": list(cfg.llm.anthropic_compat.models),
    }


def _apply_env_overrides(flat: dict[str, object]) -> dict[str, object]:
    """Let runtime-injected env vars (e.g. DATABASE_URL) win over the YAML."""
    env_map = {"DATABASE_URL": "database_url_override"}
    for env_key, settings_key in env_map.items():
        value = os.environ.get(env_key)
        if value:
            flat[settings_key] = value
    return flat


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    cfg = _load_yaml()
    flat = _apply_env_overrides(_flatten(cfg))
    # If `database.url` is set in YAML (and DATABASE_URL env is not), propagate it.
    if cfg.database.url and "database_url_override" not in flat:
        flat["database_url_override"] = cfg.database.url
    return Settings(**flat)


settings = get_settings()
