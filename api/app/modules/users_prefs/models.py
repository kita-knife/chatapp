"""UserPreference model: one row per user, JSONB blob for flexibility."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


# Default preferences for new users. Keep keys stable; the schema-less JSONB
# shape lets us evolve without migrations, but documented keys should be
# additive-only.
DEFAULT_PREFERENCES: dict = {
    "default_mode": "simple",        # 'simple' | 'knowledge' | 'think'
    "default_model": None,           # None → use settings.llm_model
    "system_prompt_overrides": {
        "think": None,
        "knowledge": None,
    },
    "ui_language": "zh",             # 'zh' | 'en'
}


def _merge_defaults(value: dict | None) -> dict:
    """Return DEFAULT_PREFERENCES deep-merged with the stored value."""
    base = {k: (v.copy() if isinstance(v, dict) else v) for k, v in DEFAULT_PREFERENCES.items()}
    if not value:
        return base
    out = dict(base)
    for k, v in value.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            merged = dict(out[k])
            merged.update(v)
            out[k] = merged
        else:
            out[k] = v
    return out


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    preferences: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def view(self) -> dict:
        """Return the preferences with defaults filled in for any missing keys."""
        return _merge_defaults(self.preferences)