"""User preferences API: self (PATCH /me/preferences) + root (GET/PATCH /users/{id}/preferences)."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import ROLE_ROOT, User
from app.modules.users_prefs import service

router = APIRouter()


class UpdatePreferencesRequest(BaseModel):
    """Partial update — only fields sent are merged. Use `replace_all=true` to wipe all."""
    preferences: dict = Field(default_factory=dict)
    replace_all: bool = Field(default=False, description="Replace the entire preferences blob instead of merging.")


@router.get("/me/preferences")
async def get_my_preferences(
    current: Annotated[User, Depends(get_current_user)],
) -> dict:
    return await service.get_preferences(current.id)


@router.patch("/me/preferences")
async def update_my_preferences(
    payload: UpdatePreferencesRequest,
    current: Annotated[User, Depends(get_current_user)],
) -> dict:
    if payload.replace_all:
        return await service.replace_preferences(current.id, payload.preferences)
    return await service.upsert_preferences(current.id, payload.preferences)


@router.get("/users/{user_id}/preferences")
async def get_user_preferences(
    user_id: UUID,
    current: Annotated[User, Depends(require_role(ROLE_ROOT))],
) -> dict:
    return await service.get_preferences(user_id)


@router.patch("/users/{user_id}/preferences")
async def update_user_preferences(
    user_id: UUID,
    payload: UpdatePreferencesRequest,
    current: Annotated[User, Depends(require_role(ROLE_ROOT))],
) -> dict:
    if payload.replace_all:
        return await service.replace_preferences(user_id, payload.preferences)
    return await service.upsert_preferences(user_id, payload.preferences)