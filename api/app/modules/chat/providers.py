"""LLM provider layer.

Iteration 1.1 design:
- Use agno for the model factory + provider resolution (per user request).
- Wrap OpenAI's streaming client directly for OpenAI-compatible endpoints
  so we can capture `usage` tokens, which agno's event abstraction hides
  during streaming. agno still drives the connectivity / non-streaming calls.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

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
        return "minimax"
    if model.startswith("gpt-") or model.startswith("o") or model.startswith("chatgpt-"):
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
    # Default fallback to the configured MiniMax endpoint if available.
    if settings.llm_api_base:
        return "minimax"
    return "openai"


def _openai_compatible(provider: str, model: str) -> tuple[str, str]:
    """Return (base_url, api_key) for OpenAI-compatible providers."""
    if provider == "minimax":
        return settings.llm_api_base, settings.llm_api_key
    if provider == "openai":
        return settings.openai_base_url or "https://api.openai.com/v1", settings.openai_api_key
    raise ProviderError(f"Provider {provider} is not OpenAI-compatible")


# ---------- Connectivity probe ----------

async def check_connectivity(provider: str, model: str) -> dict[str, Any]:
    """Quick non-streaming connectivity probe. No tokens spent."""
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

    # OpenAI-compatible: probe /models
    try:
        base_url, api_key = _openai_compatible(provider, model)
    except ProviderError as exc:
        return {"ok": False, "provider": provider, "model": model, "latency_ms": 0, "error": str(exc)}
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
    from app.core.prompts import render

    if provider == "ollama":
        async for chunk in _stream_ollama(messages, model):
            yield chunk
        return
    if provider == "anthropic":
        async for chunk in _stream_anthropic(messages, model):
            yield chunk
        return
    # OpenAI-compatible (minimax / openai)
    try:
        base_url, api_key = _openai_compatible(provider, model)
    except ProviderError as exc:
        yield ChatChunk(error=str(exc))
        yield ChatChunk(finish_reason="error")
        return
    if not api_key:
        yield ChatChunk(error=render("errors.openai_unconfigured", provider=provider))
        yield ChatChunk(finish_reason="error")
        return
    extra_system, max_tokens = _mode_overrides(mode)
    if extra_system:
        messages = _prepend_system(messages, extra_system)
    async for chunk in _stream_openai_compatible(
        base_url, api_key, messages, model, max_tokens=max_tokens
    ):
        yield chunk


def _prepend_system(
    messages: list[dict[str, str]], system_text: str
) -> list[dict[str, str]]:
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


async def _stream_openai_compatible(
    base_url: str,
    api_key: str,
    messages: list[dict[str, str]],
    model: str,
    max_tokens: int | None = None,
) -> AsyncIterator[ChatChunk]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    tokens_in = 0
    tokens_out = 0
    try:
        kwargs: dict[str, Any] = {"stream": True, "stream_options": {"include_usage": True}}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            **kwargs,
        )
        async for chunk in stream:
            if chunk.usage:
                tokens_in = max(tokens_in, int(chunk.usage.prompt_tokens or 0))
                tokens_out = max(tokens_out, int(chunk.usage.completion_tokens or 0))
            if chunk.choices:
                choice = chunk.choices[0]
                if choice.delta and choice.delta.content:
                    yield ChatChunk(delta=choice.delta.content)
                if choice.finish_reason:
                    yield ChatChunk(
                        finish_reason=choice.finish_reason,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                    )
        # No explicit finish_reason chunk was emitted (some providers skip it).
        yield ChatChunk(finish_reason="stop", tokens_in=tokens_in, tokens_out=tokens_out)
    except Exception as exc:
        yield ChatChunk(error=f"openai-compatible stream failed: {exc}", tokens_in=tokens_in, tokens_out=tokens_out)
        yield ChatChunk(finish_reason="error", tokens_in=tokens_in, tokens_out=tokens_out)


async def _stream_ollama(
    messages: list[dict[str, str]],
    model: str,
) -> AsyncIterator[ChatChunk]:
    ollama_model = model.split(":", 1)[1] if model.startswith("ollama:") else model
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{settings.ollama_base_url.rstrip('/')}/api/chat",
                json={"model": ollama_model, "messages": messages, "stream": True},
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    import json as _json

                    data = _json.loads(line)
                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield ChatChunk(delta=content)
                    if data.get("done"):
                        yield ChatChunk(finish_reason="stop")
                        return
    except Exception as exc:
        yield ChatChunk(error=f"ollama stream failed: {exc}")
        yield ChatChunk(finish_reason="error")


async def _stream_anthropic(
    messages: list[dict[str, str]],
    model: str,
) -> AsyncIterator[ChatChunk]:
    if not settings.anthropic_api_key:
        yield ChatChunk(error="ANTHROPIC_API_KEY not configured")
        yield ChatChunk(finish_reason="error")
        return
    from anthropic import AsyncAnthropic

    system = next((m["content"] for m in messages if m["role"] == "system"), None)
    chat_messages = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m["role"] in ("user", "assistant")
    ]
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    tokens_in = 0
    tokens_out = 0
    try:
        async with client.messages.stream(
            model=model,
            max_tokens=4096,
            system=system or "",
            messages=chat_messages,
        ) as stream:
            async for text in stream.text_stream:
                yield ChatChunk(delta=text)
        # usage can be retrieved from the final message after the stream.
        final = await stream.get_final_message()
        tokens_in = int(getattr(final.usage, "input_tokens", 0) or 0)
        tokens_out = int(getattr(final.usage, "output_tokens", 0) or 0)
        yield ChatChunk(finish_reason="stop", tokens_in=tokens_in, tokens_out=tokens_out)
    except Exception as exc:
        yield ChatChunk(error=f"anthropic stream failed: {exc}", tokens_in=tokens_in, tokens_out=tokens_out)
        yield ChatChunk(finish_reason="error", tokens_in=tokens_in, tokens_out=tokens_out)


# ---------- One-shot (title generation) ----------

async def complete_once(
    provider: str,
    model: str,
    prompt: str,
    max_tokens: int = 64,
) -> str:
    """One-shot non-streaming completion. Used for title generation."""
    if provider == "minimax" and not settings.llm_api_key:
        raise ProviderNotConfiguredError("LLM_API_KEY not configured")
    if provider == "openai" and not settings.openai_api_key:
        raise ProviderNotConfiguredError("OPENAI_API_KEY not configured")
    if provider == "anthropic" and not settings.anthropic_api_key:
        raise ProviderNotConfiguredError("ANTHROPIC_API_KEY not configured")

    if provider == "ollama":
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{settings.ollama_base_url.rstrip('/')}/api/chat",
                json={
                    "model": model.split(":", 1)[1] if model.startswith("ollama:") else model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
            )
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "")

    if provider == "anthropic":
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        msg = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        out: list[str] = []
        for block in msg.content:
            if getattr(block, "type", None) == "text":
                out.append(block.text)
        return "".join(out)

    # OpenAI-compatible
    base_url, api_key = _openai_compatible(provider, model)
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""
