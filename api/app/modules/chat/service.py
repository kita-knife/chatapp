"""Chat business logic: history, turn-based dispatch, streaming, auto-title."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, AsyncIterator, Tuple
from uuid import UUID

from sqlalchemy import select

from app.core.db import session_scope
from app.modules.chat.models import ChatMessage, ChatSession
from app.modules.chat.providers import (
    ChatChunk,
    complete_once,
    stream_chat_agent,
)

logger = logging.getLogger(__name__)

# Skip the LLM title refinement when the user's first message is shorter than
# this. For short messages the immediate title is already verbatim (no
# truncation), so an LLM call would just add latency + tokens without
# improving the user-visible result.
TITLE_LLM_THRESHOLD = 30

# `asyncio.create_task()` returns a Task; the asyncio runtime only holds weak
# references to tasks, so without a strong external reference the task can be
# garbage collected mid-flight. We collect in-flight title tasks here so they
# survive until completion.
_bg_title_tasks: set[asyncio.Task] = set()


def _fire_and_forget(coro: Any) -> asyncio.Task:
    """Schedule `coro` on the current event loop and retain a strong ref
    until done, so the task isn't garbage-collected mid-flight."""
    task = asyncio.create_task(coro)
    _bg_title_tasks.add(task)
    task.add_done_callback(_bg_title_tasks.discard)
    return task

StreamItem = Tuple[ChatChunk, bool, dict[str, Any]]
# Each tuple: (chunk, is_last, meta)
# meta carries: {"needs_title": bool, "model": str, "provider": str}

AUTO_TITLE_ON_FIRST_MESSAGE = True

# Tools are configured per Agent (see `app.modules.chat.agents.*`).
# Each mode's agent decides which tools to attach and which instructions
# to use. The simple agent has no tools; knowledge and think attach all
# six graph tools.

# ---------------- sessions (owner-scoped) ----------------

async def create_session(owner_id: UUID, title: str, model: str, provider: str) -> ChatSession:
    """Create a new chat session.

    The `model` column stores `"{provider}:{model}"` so the sidebar can
    show both pieces without a schema change. Old rows store a bare model
    name; `routes._session_dict` handles both forms when serialising.
    """
    async with session_scope() as session:
        cs = ChatSession(owner_id=owner_id, title=title, model=f"{provider}:{model}")
        session.add(cs)
        await session.flush()
        await session.refresh(cs)
        return cs


async def list_sessions(owner_id: UUID, limit: int = 100) -> list[ChatSession]:
    async with session_scope() as session:
        result = await session.execute(
            select(ChatSession)
            .where(ChatSession.owner_id == owner_id)
            .order_by(ChatSession.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


async def get_session(owner_id: UUID, session_id: UUID) -> ChatSession | None:
    async with session_scope() as session:
        cs = await session.get(ChatSession, session_id)
        if cs is None or cs.owner_id != owner_id:
            return None
        return cs


async def delete_session(owner_id: UUID, session_id: UUID) -> None:
    async with session_scope() as session:
        cs = await session.get(ChatSession, session_id)
        if cs is None or cs.owner_id != owner_id:
            return
        await session.delete(cs)
    # Sync-delete the agno-managed session row (conversation history +
    # session_state live there). Best effort — if agno's table is missing
    # this fails silently in the agno DB layer.
    try:
        from app.core.agno_db import get_agno_db

        await get_agno_db().delete_session(str(session_id))
    except Exception:
        logger.warning(
            "agno session cleanup failed for chat_session=%s", session_id
        )


async def list_messages(owner_id: UUID, session_id: UUID) -> list[ChatMessage]:
    async with session_scope() as session:
        cs = await session.get(ChatSession, session_id)
        if cs is None or cs.owner_id != owner_id:
            return []
        result = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
        )
        return list(result.scalars().all())


async def count_turns(session_id: UUID, session=None) -> int:
    """Count turns for a session. If a session is provided, reuse it (so we can
    count just-inserted, uncommitted rows). Otherwise open a fresh one."""
    if session is not None:
        result = await session.execute(
            select(ChatMessage.id).where(ChatMessage.session_id == session_id)
        )
        return len(result.scalars().all())
    async with session_scope() as s:
        result = await s.execute(
            select(ChatMessage.id).where(ChatMessage.session_id == session_id)
        )
        return len(result.scalars().all())


# ---------------- streaming (one row per turn) ----------------

async def stream_chat_response(
    owner_id: UUID,
    session_id: UUID,
    user_content: str,
    model: str | None = None,
    mode: str | None = None,
    project: str | None = None,
    provider: str | None = None,
) -> AsyncIterator[StreamItem]:
    """Create a single turn row (user_content filled, status=streaming), stream
    the assistant reply into the same row's assistant_content, then mark
    status=complete. Yields (chunk, is_last, meta) per token.

    If `mode` is not provided, the user's stored preference is consulted.
    Priority: explicit `mode` arg > DB preference > settings default ('simple').

    `project` (when None) is read from user_preferences.default_project —
    the library_coderag project that tools query against.
    """
    needs_title = False
    needs_title_llm = False
    effective_mode = mode
    # Step 1: insert single row + check ownership.
    async with session_scope() as session:
        cs = await session.get(ChatSession, session_id)
        if cs is None or cs.owner_id != owner_id:
            yield (ChatChunk(error="Session not found"), True, {})
            return
        # `model` is required by the route; this fallback only guards
        # direct/internal callers. The stored column is `{provider}:{model}`,
        # so split it to recover the bare model name.
        if model is None:
            stored = cs.model or ""
            used_model = stored.split(":", 1)[1] if ":" in stored else stored
        else:
            used_model = model
        # Keep the session's stored `{provider}:{model}` composite in sync
        # with this request's explicit provider/model (both required).
        stored_composite = f"{provider}:{used_model}"
        if cs.model != stored_composite:
            cs.model = stored_composite
        turn = ChatMessage(
            session_id=session_id,
            user_content=user_content,
            assistant_content="",
            status="streaming",
        )
        session.add(turn)
        await session.flush()
        await session.refresh(turn)
        turn_id = turn.id
        prior_count = await count_turns(session_id, session) - 1  # we just inserted one
        if prior_count == 0 and cs.title in ("", "New chat"):
            # Immediate fallback title (no LLM call) so the sidebar reflects
            # the topic immediately, even before the LLM stream finishes.
            cs.title = _immediate_title(user_content)
            # Skip the LLM refinement for short messages — the immediate
            # title is already verbatim (no truncation occurred), so a
            # second LLM call would just cost tokens without improving
            # the user-visible result.
            if AUTO_TITLE_ON_FIRST_MESSAGE and len(user_content.strip()) >= TITLE_LLM_THRESHOLD:
                needs_title_llm = True
        # Resolve effective mode (request > preference > default).
        if effective_mode is None:
            from app.modules.users_prefs import service as prefs_service

            prefs = await prefs_service.get_preferences(owner_id)
            pref_mode = prefs.get("default_mode")
            if pref_mode in {"simple", "knowledge", "think"}:
                effective_mode = pref_mode
        # Resolve effective model from preferences if not set by request/session.
        if model is None:
            from app.modules.users_prefs import service as prefs_service

            prefs = await prefs_service.get_preferences(owner_id)
            pref_model = prefs.get("default_model")
            if pref_model:
                used_model = pref_model
        # Resolve effective project from preferences (always read; tools
        # need it to bind `:project`). Empty string means none picked.
        if project is None:
            from app.modules.users_prefs import service as prefs_service

            prefs = await prefs_service.get_preferences(owner_id)
            project = prefs.get("default_project") or ""

    # Step 2: stream — update the row in place between chunks.
    # `provider` is now required and was sent by the frontend; the dropdown
    # is the authoritative source for which provider a model came from.
    if not provider:
        raise ValueError(
            "stream_chat_response called without provider — "
            "this is a programmer error; ChatRequest.provider is required."
        )
    provider_name = provider

    # Kick off the LLM title-refinement task in parallel with the main stream
    # below. The task opens its own DB session and writes the refined title
    # back when done. asyncio.create_task schedules it on the same event loop;
    # the iteration in Step 2 keeps yielding between chunks and the task runs
    # concurrently.
    if needs_title_llm:
        _fire_and_forget(
            generate_title_if_default(
                session_id, user_content, used_model, provider_name
            )
        )

    full_text_parts: list[str] = []
    tokens_in = 0
    tokens_out = 0
    final_reason: str | None = "stop"
    async for chunk in stream_chat_agent(
        provider_name,
        user_content,
        used_model,
        mode=effective_mode,
        project=project,
        session_id=str(session_id),
        user_id=str(owner_id),
    ):
        if chunk.delta:
            full_text_parts.append(chunk.delta)
        if chunk.tokens_in:
            tokens_in = max(tokens_in, chunk.tokens_in)
        if chunk.tokens_out:
            tokens_out = max(tokens_out, chunk.tokens_out)
        if chunk.finish_reason:
            final_reason = chunk.finish_reason
            # Persist cumulative assistant text + final tokens.
            async with session_scope() as session:
                turn = await session.get(ChatMessage, turn_id)
                if turn is not None:
                    turn.assistant_content = "".join(full_text_parts)
                    turn.user_tokens_in = tokens_in
                    turn.assistant_tokens_out = tokens_out
                    turn.status = (
                        "complete" if chunk.finish_reason == "stop" else (
                            "error" if chunk.finish_reason == "error" else "interrupted"
                        )
                    )
        is_last = bool(chunk.finish_reason)
        yield (
            chunk,
            is_last,
            {"needs_title": needs_title_llm, "model": used_model, "provider": provider_name, "effective_mode": effective_mode}
            if is_last
            else {},
        )
        if chunk.finish_reason == "error":
            return


# ---------------- auto-title ----------------

_IMMEDIATE_TITLE_MAX = 32


def _immediate_title(user_content: str, max_len: int = _IMMEDIATE_TITLE_MAX) -> str:
    """Cheap fallback for the sidebar: smart-truncate the user's first message.

    Rules:
    - Collapse whitespace (newlines → single space).
    - Strip leading/trailing whitespace.
    - If shorter than `max_len`, return verbatim.
    - Otherwise cut at the last whitespace within the limit and strip trailing
      punctuation / ellipsis-like chars. No ellipsis is added — the
      LLM-refined title replaces this within a couple of seconds.
    """
    cleaned = re.sub(r"\s+", " ", user_content.strip())
    if not cleaned:
        return "New chat"
    if len(cleaned) <= max_len:
        return cleaned
    cut = cleaned[:max_len]
    sp = cut.rfind(" ")
    # Only land on the word boundary if it doesn't chop off the first half.
    if sp >= max_len // 2:
        cut = cut[:sp]
    return cut.rstrip(" ,;:!?…。、")


async def generate_title_if_default(
    session_id: UUID,
    user_content: str,
    model: str,
    provider: str,
) -> None:
    """Background task: refine the immediate fallback title with an LLM call.

    Best-effort. Only writes if the title hasn't been manually renamed by the
    user (we detect this by comparing to the immediate fallback we just set).
    """
    try:
        new_title = await _generate_title(user_content, model, provider)
        if not new_title:
            return
        async with session_scope() as session:
            cs = await session.get(ChatSession, session_id)
            if cs is None:
                return
            # Don't overwrite if the user has manually renamed the session.
            current = (cs.title or "").strip()
            if not current or current == "New chat" or current == _immediate_title(user_content):
                cs.title = new_title[:80]
    except Exception:
        logger.exception(
            "generate_title_if_default crashed for session=%s", session_id
        )
        return


async def _generate_title(user_content: str, model: str, provider: str) -> str:
    from app.core.prompts import render

    prompt = render("titles.generate", user_content=user_content.strip())
    try:
        # 512 leaves room for MiniMax-M3's thinking block (~250-400 tokens)
        # plus the actual title output. With 128 the model frequently gets
        # truncated mid-think and emits an empty response after the think
        # block, leaving no salvageable title.
        raw = await complete_once(provider, model, prompt, max_tokens=512)
    except Exception as exc:
        logger.warning(
            "title refinement failed (provider=%s model=%s): %s",
            provider,
            model,
            exc,
        )
        return _simple_title(user_content)
    cleaned = _parse_title(raw)
    if not cleaned:
        return _simple_title(user_content)
    return cleaned[:32]


_TITLE_TAG_RE = re.compile(r"<title>\s*(.*?)\s*</title>", re.IGNORECASE | re.DOTALL)


def _parse_title(raw: str | None) -> str:
    """Extract a clean title from an LLM response.

    MiniMax-M3 emits a think block followed by the actual answer. We:
      1. Strip ``<think>...</think>`` statefully (tags may split across
         chunks in streaming responses, though we get the final non-streaming
         text here).
      2. If a ``<title>...</title>`` wrapper is present in what remains,
         extract its content (model was instructed to use this format).
      3. Otherwise clean up whatever's left (strip wrapping quotes /
         backticks, drop leading numbering, collapse whitespace).

    Returns ``""`` if nothing salvageable; caller is expected to fall back
    to a deterministic title derived from the user message.
    """
    if not raw:
        return ""
    # 1. Strip think blocks statefully.
    out: list[str] = []
    i = 0
    in_think = False
    while i < len(raw):
        if in_think:
            end = raw.find("</think>", i)
            if end == -1:
                # Unterminated think block — drop the rest.
                break
            i = end + len("</think>")
            in_think = False
            continue
        start = raw.find("<think>", i)
        if start == -1:
            out.append(raw[i:])
            break
        if start > i:
            out.append(raw[i:start])
        i = start + len("<think>")
        in_think = True
    text = "".join(out)

    # 2. Prefer <title>...</title> if the model honored the format.
    m = _TITLE_TAG_RE.search(text)
    if m:
        return _cleanup_title(m.group(1))

    # 3. Fall back to whatever's left, with normal cleanup.
    return _cleanup_title(text)


def _cleanup_title(text: str) -> str:
    """Strip wrapping quotes / backticks, drop leading numbering, collapse ws."""
    text = (text or "").strip().strip("\"'`").strip()
    if len(text) > 2 and text[0].isdigit() and text[1] in (".", ")", "、"):
        text = text[2:].strip()
    return " ".join(text.split())


def _simple_title(user_content: str) -> str:
    return _immediate_title(user_content)
