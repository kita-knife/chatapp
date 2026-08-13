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
import json
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx
from agno.models.base import Model
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.models.openai.like import OpenAILike
from agno.run import RunContext
from agno.utils.log import log_debug

from app.core.config import settings
from app.modules.chat.tools import get_tool


# Safety cap on tool-call rounds. Models that keep calling tools in a loop
# without converging are stopped after this many iterations.
_MAX_TOOL_ROUNDS = 5


@dataclass
class ChatChunk:
    delta: str = ""
    finish_reason: str | None = None
    error: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    # When the model requests a tool call we yield one chunk per call with
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

    `anthropic` and `ollama` are imported lazily with defensive `ImportError`
    handling — they are declared as dependencies in `pyproject.toml`, but
    if a deployment is mis-configured (e.g. partial install) we surface a
    friendly `ProviderNotConfiguredError` instead of a raw 500 traceback.
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
    project: str = "",
    tools: list[str] | None = None,
) -> AsyncIterator[ChatChunk]:
    """Stream a chat completion. Captures token usage from the final chunk.

    The optional `mode` argument selects a mode-specific system prompt
    (loaded from `prompts.yml`) and adjusts `max_tokens`.

    Tool calling: when `tools` is provided, the model may emit `tool_calls`
    in its response. We execute each requested tool (passing `project` via
    a `RunContext`) and feed the result back to the model in a follow-up
    call, repeating up to `_MAX_TOOL_ROUNDS` times. Each tool call / result
    is yielded as a `ChatChunk` so the frontend can show the trace.
    """
    if provider not in {"openlike", "openai", "anthropic", "ollama"}:
        yield ChatChunk(error=f"unsupported provider: {provider}")
        yield ChatChunk(finish_reason="error")
        return

    extra_system, max_tokens = _mode_overrides(mode)
    if extra_system:
        messages = _prepend_system(messages, extra_system)

    try:
        m = _build_model(provider, model)
    except ProviderNotConfiguredError as exc:
        log_debug(f"{provider} not configured: {exc}")
        yield ChatChunk(error=str(exc))
        yield ChatChunk(finish_reason="error")
        return
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

    # Convert registered tools into the list[dict] shape agno expects. agno's
    # `Model` class accepts either raw `Function` objects or pre-serialized
    # dicts; we use `Function.to_dict()` for portability across providers.
    tool_dicts: list[dict] | None = None
    if tools:
        from app.modules.chat.tools import TOOL_REGISTRY

        tool_dicts = []
        for name in tools:
            fn = TOOL_REGISTRY.get(name)
            if fn is not None and hasattr(fn, "to_dict"):
                tool_dicts.append(fn.to_dict())

    try:
        for _round in range(_MAX_TOOL_ROUNDS):
            pending_tool_calls: list[dict] = []
            async for r in m.ainvoke_stream(
                agno_msgs,
                assistant,
                tools=tool_dicts,
            ):
                content = r.content or ""
                cleaned = _strip_inline_think_tags(content, think_state)
                if cleaned:
                    yield ChatChunk(delta=cleaned)
                if r.response_usage is not None:
                    tokens_in = max(tokens_in, int(r.response_usage.input_tokens or 0))
                    tokens_out = max(tokens_out, int(r.response_usage.output_tokens or 0))
                # Collect tool-call requests (the model streams them across
                # multiple chunks; we accumulate per round).
                if r.tool_calls:
                    for tc in r.tool_calls:
                        # Each `tc` may be a dict or a FunctionCall-like;
                        # normalise to a plain dict.
                        if hasattr(tc, "model_dump"):
                            tc_dict = tc.model_dump()
                        elif hasattr(tc, "to_dict"):
                            tc_dict = tc.to_dict()
                        else:
                            tc_dict = dict(tc)
                        pending_tool_calls.append(tc_dict)

            if not pending_tool_calls:
                # No tools requested — model is done.
                break

            # Record the assistant's decision so the next round sees the
            # tool_calls as part of conversation history.
            agno_msgs.append(
                Message(
                    role="assistant",
                    content="",
                    tool_calls=pending_tool_calls,
                )
            )

            # Execute each requested tool. The helper is an async generator
            # that yields UI chunks (tool_call + tool_result) and mutates
            # `agno_msgs` with the tool's output message for the next round.
            for call in pending_tool_calls:
                async for ui_chunk in _run_tool_call(
                    call=call,
                    project=project,
                    agno_msgs=agno_msgs,
                ):
                    yield ui_chunk

        # Flush any residual non-think content held back by the tag filter.
        tail = think_state["pending"]
        if tail and not think_state["in_think"]:
            yield ChatChunk(delta=tail)
        yield ChatChunk(finish_reason="stop", tokens_in=tokens_in, tokens_out=tokens_out)
    except Exception as exc:
        log_debug(f"{provider} stream failed: {exc}")
        yield ChatChunk(error=f"{provider} stream failed: {exc}", tokens_in=tokens_in, tokens_out=tokens_out)
        yield ChatChunk(finish_reason="error", tokens_in=tokens_in, tokens_out=tokens_out)


# ---------- Tool-call execution ----------


async def _run_tool_call(
    call: dict,
    project: str,
    agno_msgs: list[Message],
) -> AsyncIterator[ChatChunk]:
    """Execute one tool call, append the result to `agno_msgs`, and yield UI chunks.

    Yields one `tool_call` chunk (sent to the client before invocation) and
    one `tool_result` chunk (sent after). On failure the result chunk
    contains the error message.

    `call` shape (after normalisation):
        {
          "id": "...",
          "type": "function",
          "function": {"name": "execute_sql", "arguments": "{...json...}"}
        }
    """
    fn_info = call.get("function") or {}
    tool_name = fn_info.get("name", "")
    raw_args = fn_info.get("arguments", "") or ""
    tool_call_id = call.get("id") or ""

    try:
        args_obj = json.loads(raw_args) if raw_args.strip() else {}
    except json.JSONDecodeError:
        args_obj = {}

    yield ChatChunk(tool_call={"id": tool_call_id, "name": tool_name, "arguments": args_obj})

    tool_func = get_tool(tool_name)
    if tool_func is None:
        result_str = json.dumps({"error": f"unknown tool: {tool_name}"})
    else:
        run_ctx = RunContext(
            run_id="chat-tool",
            session_id="chat-tool",
            session_state={"project": project},
        )
        try:
            result_str = await tool_func(**args_obj, run_context=run_ctx)
        except TypeError as exc:
            result_str = json.dumps(
                {"error": f"tool {tool_name} argument mismatch: {exc}"}
            )
        except Exception as exc:
            result_str = json.dumps({"error": f"tool {tool_name} failed: {exc}"})

    agno_msgs.append(
        Message(role="tool", tool_call_id=tool_call_id, content=result_str)
    )
    yield ChatChunk(
        tool_result={"tool_call_id": tool_call_id, "name": tool_name, "result": result_str}
    )


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
