"""Prompt loader.

All user-facing prompts are kept in a single YAML file (`prompts.yml`) and
loaded at startup. The loader supports dotted-path access (`modes.think`) and
`str.format` style placeholder substitution.

Hot-reload is optional: set `prompts_reload=true` (env `PROMPTS_RELOAD=1`) to
re-read the file on every call. Defaults to cached load at startup.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.config import settings

logger = logging.getLogger(__name__)


def _prompts_path() -> Path:
    """Resolve the prompts file path. Allows override via settings."""
    p = Path(settings.prompts_file)
    if not p.is_absolute():
        # Relative paths are resolved against the api/ root (parent of `app/`).
        # `prompts.py` lives at `api/app/core/prompts.py`, so go up two levels.
        p = Path(__file__).resolve().parent.parent.parent / p
    return p


def _load_from_disk() -> dict[str, Any]:
    path = _prompts_path()
    if not path.exists():
        logger.warning("prompts file missing at %s — using empty dict", path)
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        logger.warning("prompts file at %s did not parse to dict — ignoring", path)
        return {}
    return data


@lru_cache(maxsize=1)
def _cached_load() -> dict[str, Any]:
    return _load_from_disk()


def get_prompts() -> dict[str, Any]:
    """Return the full prompts dict.

    If `prompts_reload` is enabled, the cache is bypassed so callers always
    see the latest file content.
    """
    if settings.prompts_reload:
        return _load_from_disk()
    return _cached_load()


def reload_prompts() -> None:
    """Force re-read from disk (used by tests and by the hot-reload loop)."""
    _cached_load.cache_clear()


def get(name: str, default: str = "") -> str:
    """Look up a prompt by dotted path.

    Example: `get("modes.think")`, `get("errors.openai_unreachable")`.
    Returns the provided default if the path is missing or non-string.
    """
    cur: Any = get_prompts()
    for part in name.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    if not isinstance(cur, str):
        return default
    return cur


def render(name: str, /, **kwargs: Any) -> str:
    """Look up a prompt and substitute `**kwargs` placeholders.

    If a placeholder is missing in `kwargs`, it is left in place rather than
    raising — this lets callers pass partial overrides safely.
    """
    template = get(name)
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template