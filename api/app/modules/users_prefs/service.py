"""User preferences service: read / merge / replace."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db import session_scope
from app.modules.users_prefs.models import DEFAULT_PREFERENCES, UserPreference


async def get_preferences(user_id: UUID) -> dict:
    """Return the user's effective preferences (defaults merged in).

    When the user has never set `default_model`, fall back to the first
    model in `config.yml#llm.openlike.models` (the openlike default) so the
    frontend always sees a concrete value. The DB row is NOT mutated —
    explicit user choices still win on next read.
    """
    async with session_scope() as session:
        result = await session.execute(
            select(UserPreference).where(UserPreference.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            prefs = dict(DEFAULT_PREFERENCES)
        else:
            prefs = row.view()

    if not prefs.get("default_model"):
        from app.core.config import settings

        if settings.openlike_models:
            prefs["default_model"] = settings.openlike_models[0]

    return prefs


async def get_raw_preferences(user_id: UUID) -> dict:
    """Return the user's raw stored preferences (no defaults merged)."""
    async with session_scope() as session:
        result = await session.execute(
            select(UserPreference).where(UserPreference.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        return dict(row.preferences) if row else {}


def _deep_merge(base: dict, patch: dict) -> dict:
    """Deep-merge `patch` into `base` (dicts merged recursively)."""
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


async def upsert_preferences(user_id: UUID, patch: dict) -> dict:
    """Deep-merge `patch` into the user's preferences; create if missing.

    Returns the merged effective preferences.
    """
    async with session_scope() as session:
        result = await session.execute(
            select(UserPreference).where(UserPreference.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            # Upsert: start with defaults, then merge patch.
            merged = _deep_merge(dict(DEFAULT_PREFERENCES), patch)
            row = UserPreference(user_id=user_id, preferences=merged)
            session.add(row)
            await session.flush()
        else:
            row.preferences = _deep_merge(dict(row.preferences), patch)
            await session.flush()
        return row.view()


async def replace_preferences(user_id: UUID, value: dict) -> dict:
    """Replace the user's preferences wholesale (with defaults filled)."""
    async with session_scope() as session:
        result = await session.execute(
            select(UserPreference).where(UserPreference.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = UserPreference(user_id=user_id, preferences=value)
            session.add(row)
        else:
            row.preferences = dict(value)
        await session.flush()
        return row.view()