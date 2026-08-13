"""LLM provider layer via agno.

We use agno's `Model` classes (OpenAIChat / OpenAILike / Claude / OllamaChat)
as the provider abstraction instead of calling openai / anthropic / httpx SDKs
directly. Each `Model` exposes `ainvoke_stream()` (async streaming) and
`ainvoke()` (one-shot), and yields `ModelResponse` with a unified
`response_usage: MessageMetrics` field — so token accounting is consistent
across providers without per-provider boilerplate.

The public API (`stream_chat`, `complete_once`, `check_connectivity`,
`ChatChunk`, `resolve_provider_for_model`) is unchanged, so service.py /
routes.py need no edits.

Provider dispatch:
    model-prefix → provider-key:
        "minimax*"       → "openlike"   (uses settings.openlike_*)
        "gpt-*", "o*",
        "chatgpt-*"      → "openai"
        "claude*"        → "anthropic"
        "ollama:*", "llama*",
        "qwen*", "mistral*" → "ollama"
        fallback         → "openlike" if settings.openlike_api_base, else "openai"
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx
from agno.models.base import Model
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.models.openai.like import OpenAILike
from agno.utils.log import log_debug

from app.core.config import settings


@dataclass
class ChatChunk:
    delta: str = ""
    finish_reason: str | None = None
    error: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0


class ProviderError(Exception):
    pass


class ProviderNotConfiguredError(ProviderError):
    pass


# ---------- Provider dispatch ----------


def resolve_provider_for_model(model: str) -> str:
    """Map a model identifier to a provider key."""
    lower = model.lower()
    if lower.startswith("minimax"):
        return "openlike"
    if (
        model.startswith("gpt-")
        or model.startswith("chatgpt-")
        # OpenAI o-series (o1, o3, o4, ...) — must NOT match `ollama:`,
        # so the prefix is checked AFTER the ollama branch below.
        or (model.startswith("o") and not model.startswith("ollama:") and len(model) > 1 and model[1].isdigit())
    ):
        return "openai"
    if model.startswith("claude"):
        return "anthropic"
    if (
        model.startswith("ollama:")
        or model.startswith("llama")
        or model.startswith("qwen")
        or model.startswith("mistral")
    ):
        return "ollama"
    if settings.openlike_api_base:
        return "openlike"
    return "openai"


def _build_model(provider: str, model: str) -> Model:
    """Construct an agno Model for the given provider.

    The underlying HTTP client is cached inside the Model instance by agno,
    so per-request construction is cheap. Retries are disabled to avoid
    duplicate token charges; we surface failures via the `error` chunk
    path so the SSE stream still completes cleanly.

    `anthropic` and `ollama` are imported lazily so projects that don't use
    those providers don't need those packages installed.
    """
    if provider == "openlike":
        return OpenAILike(
            id=model,
            name="OpenAILike",
            api_key=settings.openlike_api_key,
            base_url=settings.openlike_api_base,
            retries=0,
            retry_with_guidance=False,
        )
    if provider == "openai":
        return OpenAIChat(
            id=model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or "https://api.openai.com/v1",
            retries=0,
            retry_with_guidance=False,
        )
    if provider == "anthropic":
        from agno.models.anthropic import Claude

        return Claude(
            id=model,
            api_key=settings.anthropic_api_key,
            retries=0,
            retry_with_guidance=False,
        )
    if provider == "ollama":
        from agno.models.ollama import OllamaChat

        return OllamaChat(
            id=model,
            host=settings.ollama_base_url,
            retries=0,
            retry_with_guidance=False,
        )
    raise ProviderError(f"unknown provider: {provider}")


# ---------- Adapters between dict-shaped messages and agno's Message ----------

_VALID_ROLES = {"system", "user", "assistant", "tool"}


def _to_agno_messages(history: list[dict[str, str]]) -> list[Message]:
    out: list[Message] = []
    for m in history:
        role = m.get("role", "user")
        if role not in _VALID_ROLES:
            role = "user"
        content = m.get("content") or ""
        out.append(Message(role=role, content=content))
    return out


def _prepend_system(messages: list[dict[str, str]], system_text: str) -> list[dict[str, str]]:
    """Insert a system message at the beginning, merging if one exists."""
    if not system_text:
        return messages
    if messages and messages[0].get("role") == "system":
        merged = (messages[0].get("content") or "") + "\n\n" + system_text
        return [{"role": "system", "content": merged}] + messages[1:]
    return [{"role": "system", "content": system_text}] + list(messages)


def _mode_overrides(mode: str | None) -> tuple[str, int | None]:
    """Return (extra_system_text, max_tokens) for the given agent mode."""
    from app.core.prompts import get

    if mode == "think":
        return get("modes.think"), 4096
    if mode == "knowledge":
        prefix = get("modes.knowledge.prefix")
        suffix = get("modes.knowledge.suffix")
        return f"{prefix}\n\n{suffix}", None
    return "", None


# ---------- Inline think-tag stripper ----------

# MiniMax-M3 streams `<think>...</think>` blocks inline in content. Tags may
# split across chunks, so we maintain a tiny state machine across calls. Other
# providers (OpenAI / Anthropic / Ollama) don't emit these tags, so the
# filter is a no-op for them.

_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


def _strip_inline_think_tags(content: str, state: dict[str, Any]) -> str:
    """Filter `<think>...</think>` blocks from `content` in place.

    `state` is mutated: `state["in_think"]` tracks inside-of-block; the small
    `state["pending"]` buffer holds back a trailing tag-prefix that may
    complete on the next chunk.
    """
    if not content:
        return ""
    buf = state["pending"] + content
    state["pending"] = ""
    out: list[str] = []
    while buf:
        if state["in_think"]:
            idx = buf.find(_THINK_CLOSE)
            if idx == -1:
                keep = _trailing_tag_prefix(buf, _THINK_CLOSE)
                if keep:
                    state["pending"] = buf[-keep:]
                buf = ""
            else:
                buf = buf[idx + len(_THINK_CLOSE) :]
                state["in_think"] = False
        else:
            idx = buf.find(_THINK_OPEN)
            if idx == -1:
                keep = _trailing_tag_prefix(buf, _THINK_OPEN)
                if keep:
                    out.append(buf[:-keep])
                    state["pending"] = buf[-keep:]
                else:
                    out.append(buf)
                buf = ""
            else:
                out.append(buf[:idx])
                buf = buf[idx + len(_THINK_OPEN) :]
                state["in_think"] = True
    return "".join(out)


def _trailing_tag_prefix(s: str, tag: str) -> int:
    """Length of the longest non-empty proper prefix of `tag` that `s` ends with."""
    max_n = min(len(s), len(tag) - 1)
    for n in range(max_n, 0, -1):
        if s.endswith(tag[:n]):
            return n
    return 0


# ---------- Streaming ----------


async def stream_chat(
    provider: str,
    messages: list[dict[str, str]],
    model: str,
    mode: str | None = None,
) -> AsyncIterator[ChatChunk]:
    """Stream a chat completion. Captures token usage from the final chunk.

    The optional `mode` argument selects a mode-specific system prompt
    (loaded from `prompts.yml`) and adjusts `max_tokens`.
    """
    if provider not in {"openlike", "openai", "anthropic", "ollama"}:
        yield ChatChunk(error=f"unsupported provider: {provider}")
        yield ChatChunk(finish_reason="error")
        return

    extra_system, max_tokens = _mode_overrides(mode)
    if extra_system:
        messages = _prepend_system(messages, extra_system)

    m = _build_model(provider, model)
    if max_tokens is not None and hasattr(m, "max_tokens"):
        m.max_tokens = max_tokens

    # agno requires a pre-allocated assistant message whose `metrics` it will
    # populate with timing info; we ignore that here (our own token counters
    # come from `response_usage`).
    assistant = Message(role="assistant")
    agno_msgs = _to_agno_messages(messages)
    tokens_in = 0
    tokens_out = 0
    think_state: dict[str, Any] = {"in_think": False, "pending": ""}

    try:
        async for r in m.ainvoke_stream(agno_msgs, assistant):
            content = r.content or ""
            cleaned = _strip_inline_think_tags(content, think_state)
            if cleaned:
                yield ChatChunk(delta=cleaned)
            if r.response_usage is not None:
                tokens_in = max(tokens_in, int(r.response_usage.input_tokens or 0))
                tokens_out = max(tokens_out, int(r.response_usage.output_tokens or 0))
        # Flush any residual non-think content held back by the tag filter.
        tail = think_state["pending"]
        if tail and not think_state["in_think"]:
            yield ChatChunk(delta=tail)
        yield ChatChunk(finish_reason="stop", tokens_in=tokens_in, tokens_out=tokens_out)
    except Exception as exc:
        log_debug(f"{provider} stream failed: {exc}")
        yield ChatChunk(error=f"{provider} stream failed: {exc}", tokens_in=tokens_in, tokens_out=tokens_out)
        yield ChatChunk(finish_reason="error", tokens_in=tokens_in, tokens_out=tokens_out)


# ---------- One-shot (title generation) ----------


async def complete_once(
    provider: str,
    model: str,
    prompt: str,
    max_tokens: int = 64,
) -> str:
    """One-shot non-streaming completion. Used for title generation."""
    if provider == "openlike" and not settings.openlike_api_key:
        raise ProviderNotConfiguredError("OPENLIKE_API_KEY not configured")
    if provider == "openai" and not settings.openai_api_key:
        raise ProviderNotConfiguredError("OPENAI_API_KEY not configured")
    if provider == "anthropic" and not settings.anthropic_api_key:
        raise ProviderNotConfiguredError("ANTHROPIC_API_KEY not configured")

    m = _build_model(provider, model)
    if hasattr(m, "max_tokens"):
        m.max_tokens = max_tokens

    agno_msgs = _to_agno_messages([{"role": "user", "content": prompt}])
    r = await m.ainvoke(agno_msgs, Message(role="assistant"))
    return r.content or ""


# ---------- Connectivity probe (HTTP, no agno invocation — avoids token spend) ----------


async def check_connectivity(provider: str, model: str) -> dict[str, Any]:
    """Quick non-streaming connectivity probe. No tokens spent.

    Goes straight to the provider's HTTP endpoint instead of invoking agno,
    so a cold-start connectivity check never produces a real model call.
    """
    if provider == "ollama":
        try:
            loop = asyncio.get_event_loop()
            start = loop.time()
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
                resp.raise_for_status()
            return {
                "ok": True,
                "provider": provider,
                "model": model,
                "latency_ms": int((loop.time() - start) * 1000),
                "error": None,
            }
        except Exception as exc:
            return {
                "ok": False,
                "provider": provider,
                "model": model,
                "latency_ms": 0,
                "error": f"ollama unreachable: {exc}",
            }
    if provider == "anthropic":
        return {
            "ok": bool(settings.anthropic_api_key),
            "provider": provider,
            "model": model,
            "latency_ms": 0,
            "error": None if settings.anthropic_api_key else "ANTHROPIC_API_KEY not configured",
        }

    # OpenAI-compatible (openlike / openai): probe /models with Bearer auth.
    if provider == "openlike":
        base_url = settings.openlike_api_base
        api_key = settings.openlike_api_key
    elif provider == "openai":
        base_url = settings.openai_base_url or "https://api.openai.com/v1"
        api_key = settings.openai_api_key
    else:
        return {
            "ok": False,
            "provider": provider,
            "model": model,
            "latency_ms": 0,
            "error": f"Provider {provider} is not OpenAI-compatible",
        }

    if not api_key:
        return {
            "ok": False,
            "provider": provider,
            "model": model,
            "latency_ms": 0,
            "error": f"API key not configured for {provider}",
        }
    try:
        loop = asyncio.get_event_loop()
        start = loop.time()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
        return {
            "ok": True,
            "provider": provider,
            "model": model,
            "latency_ms": int((loop.time() - start) * 1000),
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "provider": provider,
            "model": model,
            "latency_ms": 0,
            "error": f"{provider} unreachable: {exc}",
        }
