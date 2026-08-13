"""Shared utilities for the chat module."""
from __future__ import annotations

import json
from typing import Any


def check_and_truncate_output(value: Any, max_length: int = 5000) -> str:
    """Return a JSON-encoded string of `value`, truncated to `max_length` chars.

    Tool results that go back to the LLM must be strings, and oversized
    results blow the model's context window. We JSON-encode then truncate
    with a clear marker so the LLM knows it hit a limit.
    """
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) <= max_length:
        return text
    return text[:max_length] + f"\n\n... [truncated, original length={len(text)}]"
