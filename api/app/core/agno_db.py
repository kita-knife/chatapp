"""agno Agent DB — persistent session/memory backing for the chat agents.

We let agno manage its own tables under a dedicated `agno` PostgreSQL
schema (separate from our business `ai` schema) so its 20+ tables never
collide with our Alembic-managed models. The schema + tables are created
lazily by `AsyncPostgresDb` on first use (`create_schema=True`).

Connection: we share the app's existing async engine (from
`app.core.db`) rather than spinning up a second pool. Engine disposal is
owned by `app.core.db.dispose_engine()`; do NOT call `agno_db.close()`
at shutdown (it would dispose the shared engine).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agno.db.postgres import AsyncPostgresDb

from app.core.db import init_engine as _init_app_engine

_AGNO_SCHEMA = "agno"

_agno_db: AsyncPostgresDb | None = None


def get_agno_db() -> AsyncPostgresDb:
    """Return the singleton agno `AsyncPostgresDb`. Lazily initializes."""
    global _agno_db
    if _agno_db is None:
        from agno.db.postgres import AsyncPostgresDb

        engine = _init_app_engine()  # shared engine (idempotent)
        _agno_db = AsyncPostgresDb(
            db_engine=engine,
            db_schema=_AGNO_SCHEMA,
            create_schema=True,
        )
    return _agno_db


def reset_agno_db() -> None:
    """Drop the cached instance (used by tests). Does NOT dispose the engine."""
    global _agno_db
    _agno_db = None
