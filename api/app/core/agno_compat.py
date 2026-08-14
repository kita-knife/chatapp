"""Small compatibility patches for upstream agno behaviour.

Currently contains a single patch: Claude's message formatter crashes
with a pydantic `ValidationError` when it tries to rebuild a
`ThinkingBlock` for an assistant message that has `reasoning_content`
but no `signature` in `provider_data` (signature=None). This happens
when a session's history contains thinking content produced by a
DIFFERENT provider (e.g. qwen3.8-max via dashscope's OpenAI-compatible
endpoint), and the user then switches to the anthropic provider — the
Anthropic formatter requires `signature: str` (anthropic SDK's
`ThinkingBlock` model).

The patch strips `reasoning_content` from assistant messages whose
`provider_data` lacks a signature, so no `ThinkingBlock` is constructed
with a None signature. Messages that DO carry a signature are left
untouched (their thinking is preserved).
"""
from __future__ import annotations

import agno.models.anthropic.claude as _claude_module

_original_format_messages = _claude_module.format_messages
_patched = False


def _patched_format_messages(messages, **kwargs):
    for m in messages:
        if getattr(m, "role", None) == "assistant" and getattr(m, "reasoning_content", None):
            provider_data = getattr(m, "provider_data", None) or {}
            if not provider_data.get("signature"):
                # No signature → the anthropic formatter would build
                # ThinkingBlock(signature=None) and crash. Drop the
                # reasoning instead (it's transient context, not required
                # for correctness).
                m.reasoning_content = None
                m.redacted_reasoning_content = None
    return _original_format_messages(messages, **kwargs)


def apply_agno_patches() -> None:
    """Install the format_messages patch. Idempotent."""
    global _patched
    if _patched:
        return
    _claude_module.format_messages = _patched_format_messages
    _patched = True
