"""Chat API routes (auth-protected, owner-scoped)."""
from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import settings
from app.core.db import session_scope
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.chat import service
from app.modules.chat.models import ChatMessage, ChatSession
from app.modules.chat.providers import check_connectivity, resolve_provider_for_model

router = APIRouter()


class CreateSessionRequest(BaseModel):
    title: str | None = None
    model: str | None = None


class ChatRequest(BaseModel):
    content: str
    model: str | None = None
    mode: str | None = None  # 'simple' | 'knowledge' | 'think' — reserved for future agent modes
    project: str | None = None  # override user_pref default_project for this request


def _session_dict(cs: ChatSession) -> dict:
    return {
        "id": str(cs.id),
        "title": cs.title,
        "model": cs.model,
        "owner_id": str(cs.owner_id) if cs.owner_id else None,
        "created_at": cs.created_at.isoformat(),
        "updated_at": cs.updated_at.isoformat(),
    }


def _turn_dict(m: ChatMessage) -> dict:
    return {
        "id": str(m.id),
        "session_id": str(m.session_id),
        "user_content": m.user_content,
        "assistant_content": m.assistant_content,
        "user_tokens_in": m.user_tokens_in,
        "assistant_tokens_out": m.assistant_tokens_out,
        "status": m.status,
        "created_at": m.created_at.isoformat(),
        "updated_at": m.updated_at.isoformat(),
    }


@router.get("/models")
async def get_models(current: Annotated[User, Depends(get_current_user)]) -> list[dict]:
    models: list[dict[str, str]] = []
    if settings.openlike_model:
        models.append({"provider": "openlike", "model": settings.openlike_model})
    if settings.openai_default_model:
        models.append({"provider": "openai", "model": settings.openai_default_model})
    if settings.ollama_default_model:
        models.append({"provider": "ollama", "model": settings.ollama_default_model})
    if settings.anthropic_default_model:
        models.append({"provider": "anthropic", "model": settings.anthropic_default_model})
    if not models:
        models.append({"provider": "openlike", "model": "MiniMax-M3"})
    return models


@router.get("/projects")
async def list_graph_projects(
    current: Annotated[User, Depends(get_current_user)],
) -> list[str]:
    """Distinct project names available in `library_coderag.graph_folders`.

    These populate the project dropdown in ChatInput. The user picks one
    per session; the choice is persisted in `user_preferences.default_project`
    and used to bind the `:project` placeholder in tool queries.
    """
    async with session_scope() as session:
        result = await session.execute(
            text(
                f"SELECT DISTINCT project FROM {settings.graph_schema}.graph_folders "
                "ORDER BY project"
            )
        )
        return [row[0] for row in result.fetchall() if row[0]]


@router.get("/connectivity")
async def connectivity(
    model: str = Query(default=""),
    current: Annotated[User, Depends(get_current_user)] = None,  # noqa: B008
) -> dict:
    target = model or settings.openlike_model
    provider = resolve_provider_for_model(target)
    return await check_connectivity(provider, target)


@router.post("/sessions", status_code=201)
async def create_session(
    payload: CreateSessionRequest,
    current: Annotated[User, Depends(get_current_user)],
) -> dict:
    cs = await service.create_session(
        owner_id=current.id,
        title=payload.title or "New chat",
        model=payload.model or settings.openlike_model,
    )
    return _session_dict(cs)


@router.get("/sessions")
async def list_sessions(current: Annotated[User, Depends(get_current_user)]) -> list[dict]:
    rows = await service.list_sessions(current.id)
    return [_session_dict(s) for s in rows]


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
) -> dict:
    cs = await service.get_session(current.id, session_id)
    if cs is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_dict(cs)


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
) -> dict:
    await service.delete_session(current.id, session_id)
    return {"status": "ok"}


@router.get("/sessions/{session_id}/messages")
async def list_messages(
    session_id: UUID,
    current: Annotated[User, Depends(get_current_user)],
) -> list[dict]:
    rows = await service.list_messages(current.id, session_id)
    return [_turn_dict(m) for m in rows]


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: UUID,
    payload: ChatRequest,
    current: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    async def event_stream():
        async for chunk, is_last, meta in service.stream_chat_response(
            owner_id=current.id,
            session_id=session_id,
            user_content=payload.content,
            model=payload.model,
            mode=payload.mode,
            project=payload.project,
        ):
            # First iteration is_last=True carries the resolved mode; log it.
            if is_last and meta.get("effective_mode"):
                import logging

                logging.getLogger(__name__).info(
                    "chat_request effective_mode=%s provider=%s model=%s",
                    meta["effective_mode"],
                    meta["provider"],
                    meta["model"],
                )
            data = {
                "delta": chunk.delta,
                "finish_reason": chunk.finish_reason,
                "error": chunk.error,
                "tokens_in": chunk.tokens_in,
                "tokens_out": chunk.tokens_out,
                "tool_call": chunk.tool_call,
                "tool_result": chunk.tool_result,
            }
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
