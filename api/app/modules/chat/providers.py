"""LLM provider layer via agno.

We use agno's `Model` classes (OpenAIChat / OpenAILike / Claude / OllamaChat)
as the provider abstraction for direct calls (one-shot completions,
connectivity probe), and agno's `Agent` (in `app.modules.chat.agents`) for
streaming chat with tool calling.

The public API (`ChatChunk`, `resolve_provider_for_model`,
`complete_once`, `check_connectivity`, `stream_chat_agent`) is what
service.py / routes.py consume.

Provider dispatch (model-prefix → provider-key):
    "minimax*"       → "openlike"   (uses settings.openlike_*)
    "gpt-*", "o*", "chatgpt-*" → "openai"
    "claude*"        → "anthropic"
    "ollama:*", "llama*", "qwen*", "mistral*" → "ollama"
    fallback         → "openlike" if settings.openlike_api_base, else "openai"
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx
from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.base import Model
from agno.models.message import Message
from agno.models.ollama import Ollama
from agno.models.openai import OpenAIChat
from agno.models.openai.like import OpenAILike
from agno.utils.log import log_debug

from app.core.config import settings
from app.modules.chat.agents import (
    build_knowledge_agent,
    build_simple_agent,
    build_think_agent,
)


@dataclass
class ChatChunk:
    delta: str = ""
    finish_reason: str | None = None
    error: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    # When the agent emits a tool_call we yield one chunk per call with
    # {id, name, arguments}; when the tool finishes we yield one chunk per
    # call with {tool_call_id, name, result}.
    tool_call: dict | None = None
    tool_result: dict | None = None


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
    if model.startswith("gpt-") or model.startswith("chatgpt-"):
        return "openai"
    if (
        model.startswith("o")
        and not model.startswith("ollama:")
        and len(model) > 1
        and model[1].isdigit()
    ):
        # OpenAI o-series (o1, o3, o4, ...); exclude `ollama:`.
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
    """Construct an agno `Model` for the given provider.

    The underlying HTTP client is cached inside the Model instance by agno,
    so per-request construction is cheap. Retries are disabled to avoid
    duplicate token charges; failures surface via the `error` chunk path
    so the SSE stream still completes cleanly. The anthropic / ollama
    Python packages are imported lazily so deployments that only use a
    subset of providers don't need them installed.
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
        try:
            from agno.models.anthropic import Claude
        except ImportError as exc:
            raise ProviderNotConfiguredError(
                f"anthropic Python package not installed. "
                f"Run `cd api && uv add anthropic` to enable provider '{provider}'."
            ) from exc
        return Claude(
            id=model,
            api_key=settings.anthropic_api_key,
            retries=0,
            retry_with_guidance=False,
        )
    if provider == "ollama":
        try:
            from agno.models.ollama import Ollama
        except ImportError as exc:
            raise ProviderNotConfiguredError(
                f"ollama Python package not installed. "
                f"Run `cd api && uv add ollama` to enable provider '{provider}'."
            ) from exc
        return Ollama(
            id=model,
            host=settings.ollama_base_url,
            retries=0,
            retry_with_guidance=False,
        )
    raise ProviderError(f"unknown provider: {provider}")


# ---------- Agent factory (mode-specific) ----------


_AGENT_BUILDERS = {
    "simple": build_simple_agent,
    "knowledge": build_knowledge_agent,
    "think": build_think_agent,
}


def _get_agent(model_obj: Model, mode: str, project: str = "") -> Agent:
    """Build the per-mode `Agent` instance.

    Each call constructs a fresh agent (no caching — construction is
    cheap). Tools and instructions are encapsulated in the builder
    functions under `app.modules.chat.agents.*`.

    `project` is forwarded to the builders so they can inject the active
    project name into the agent's instructions — `project_whole_index_retriever`
    expects the LLM to pass it explicitly (its cache key includes it).
    """
    mode = mode or "simple"
    builder = _AGENT_BUILDERS.get(mode)
    if builder is None:
        raise ProviderError(f"unknown mode: {mode}")
    return builder(model_obj, project=project)


# ---------- Inline think-tag stripper ----------

# MiniMax-M3 streams `<think>...</think>` blocks inline in content. Tags may
# split across chunks, so we maintain a tiny state machine across calls.
# Other providers (OpenAI / Anthropic / Ollama) don't emit these tags, so
# the filter is a no-op for them.

_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


def _strip_inline_think_tags(content: str, state: dict[str, Any]) -> str:
    """Filter `<think>...</think>` blocks from `content` in place.

    `state` is mutated: `state["in_think"]` tracks inside-of-block; the
    small `state["pending"]` buffer holds back a trailing tag-prefix that
    may complete on the next chunk.
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


# ---------- Message conversion ----------


def _dict_to_message(d: dict[str, str]) -> Message:
    """Translate a dict-shaped history entry to an agno `Message`.

    Roles outside the valid set are coerced to `user` — agents tend to
    treat unknown roles as instructions, which is the wrong default.
    """
    role = d.get("role", "user")
    if role not in {"system", "user", "assistant", "tool"}:
        role = "user"
    return Message(role=role, content=d.get("content") or "")


# ---------- Streaming via agno Agent ----------


async def stream_chat_agent(
    provider: str,
    messages: list[dict[str, str]],
    model: str,
    mode: str | None = None,
    project: str = "",
) -> AsyncIterator[ChatChunk]:
    """Stream a chat completion via agno's `Agent` + tool calling.

    The agent handles the entire tool-call loop internally; we just
    translate its event stream into our `ChatChunk` SSE format.

    `project` is bound into the agent's session_state and forwarded to
    every tool via `RunContext` so the SQL `:project` placeholder has
    a value.
    """
    if provider not in {"openlike", "openai", "anthropic", "ollama"}:
        yield ChatChunk(error=f"unsupported provider: {provider}")
        yield ChatChunk(finish_reason="error")
        return
    if not project:
        yield ChatChunk(
            error="no project selected. Pick a project from the chat input bar."
        )
        yield ChatChunk(finish_reason="error")
        return

    model_obj = _build_model(provider, model)
    try:
        agent = _get_agent(model_obj, mode or "simple", project=project)
    except ProviderError as exc:
        yield ChatChunk(error=str(exc))
        yield ChatChunk(finish_reason="error")
        return

    history = [_dict_to_message(d) for d in messages]
    think_state: dict[str, Any] = {"in_think": False, "pending": ""}
    tokens_in = 0
    tokens_out = 0

    try:
        async for event in agent.arun(
            input=history,
            stream=True,
            stream_events=True,
            session_state={"project": project},
        ):
            # agno `RunEvent` enum values are CamelCase ("RunContent",
            # "ToolCallStarted", ...). The exact strings come from
            # `agno.run.agent.RunEvent.<member>.value`.
            etype = getattr(event, "event", "")
            if etype == "RunContent":
                content = getattr(event, "content", None) or ""
                cleaned = _strip_inline_think_tags(content, think_state)
                if cleaned:
                    yield ChatChunk(delta=cleaned)
            elif etype == "ToolCallStarted":
                tool = getattr(event, "tool", None)
                if tool is not None:
                    yield ChatChunk(
                        tool_call={
                            "id": tool.tool_call_id,
                            "name": tool.tool_name,
                            "arguments": tool.tool_args or {},
                        }
                    )
            elif etype == "ToolCallCompleted":
                tool = getattr(event, "tool", None)
                if tool is not None:
                    yield ChatChunk(
                        tool_result={
                            "tool_call_id": tool.tool_call_id,
                            "name": tool.tool_name,
                            "result": str(tool.result or ""),
                        }
                    )
            elif etype == "ToolCallError":
                tool = getattr(event, "tool", None)
                name = getattr(tool, "tool_name", "?") if tool else "?"
                err = getattr(event, "error", "tool failed")
                yield ChatChunk(error=f"{name}: {err}")
            elif etype == "ModelRequestCompleted":
                tokens_in = max(tokens_in, int(event.input_tokens or 0))
                tokens_out = max(tokens_out, int(event.output_tokens or 0))
            elif etype == "RunCompleted":
                yield ChatChunk(
                    finish_reason="stop",
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                )
            elif etype == "RunError":
                err = getattr(event, "error", None) or "agent run failed"
                yield ChatChunk(error=str(err))
                yield ChatChunk(
                    finish_reason="error",
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                )

        # Flush any residual content held back by the think-tag filter.
        tail = think_state["pending"]
        if tail and not think_state["in_think"]:
            yield ChatChunk(delta=tail)
    except Exception as exc:
        log_debug(f"{provider} agent failed: {exc}")
        yield ChatChunk(error=f"{provider} agent failed: {exc}")
        yield ChatChunk(
            finish_reason="error", tokens_in=tokens_in, tokens_out=tokens_out
        )


# ---------- One-shot (title generation) ----------


async def complete_once(
    provider: str,
    model: str,
    prompt: str,
    max_tokens: int = 64,
) -> str:
    """One-shot non-streaming completion. Used for title generation.

    Doesn't go through an Agent — direct Model.ainvoke keeps token usage
    small and avoids the tool-loop machinery.
    """
    if provider == "openlike" and not settings.openlike_api_key:
        raise ProviderNotConfiguredError("OPENLIKE_API_KEY not configured")
    if provider == "openai" and not settings.openai_api_key:
        raise ProviderNotConfiguredError("OPENAI_API_KEY not configured")
    if provider == "anthropic" and not settings.anthropic_api_key:
        raise ProviderNotConfiguredError("ANTHROPIC_API_KEY not configured")

    m = _build_model(provider, model)
    if hasattr(m, "max_tokens"):
        m.max_tokens = max_tokens

    history = [_dict_to_message({"role": "user", "content": prompt})]
    r = await m.ainvoke(history, Message(role="assistant"))
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
                resp = await client.get(
                    f"{settings.ollama_base_url.rstrip('/')}/api/tags"
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
                "error": f"ollama unreachable: {exc}",
            }
    if provider == "anthropic":
        return {
            "ok": bool(settings.anthropic_api_key),
            "provider": provider,
            "model": model,
            "latency_ms": 0,
            "error": (
                None
                if settings.anthropic_api_key
                else "ANTHROPIC_API_KEY not configured"
            ),
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
