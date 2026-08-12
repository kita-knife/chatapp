"""User management API (root only)."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.modules.auth import service
from app.modules.auth.dependencies import get_current_user, require_role
from app.modules.auth.models import ROLE_ADMIN, ROLE_ROOT, ROLE_USER, User

router = APIRouter()


VALID_CREATABLE_ROLES = (ROLE_ADMIN, ROLE_USER)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=settings.root_username_min_len, max_length=64)
    password: str = Field(min_length=settings.root_password_min_len, max_length=128)
    role: str = Field(default=ROLE_USER)


class ChangePasswordRequest(BaseModel):
    new_password: str = Field(min_length=settings.root_password_min_len, max_length=128)


def _to_dict(u: User) -> dict:
    return {
        "id": str(u.id),
        "username": u.username,
        "role": u.role,
        "created_at": u.created_at.isoformat(),
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


@router.get("/users")
async def list_users(
    current: Annotated[User, Depends(require_role(ROLE_ROOT))],
) -> list[dict]:
    users = await service.list_users()
    return [_to_dict(u) for u in users]


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: CreateUserRequest,
    current: Annotated[User, Depends(require_role(ROLE_ROOT))],
) -> dict:
    if payload.role not in VALID_CREATABLE_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"role must be one of {list(VALID_CREATABLE_ROLES)}",
        )
    try:
        user = await service.create_user(payload.username, payload.password, payload.role)
    except service.UsernameTakenError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_dict(user)


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: UUID,
    current: Annotated[User, Depends(require_role(ROLE_ROOT))],
) -> dict:
    if user_id == current.id:
        raise HTTPException(status_code=400, detail="cannot delete yourself")
    target = await service.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    if target.role == ROLE_ROOT:
        # Allow deleting root, but never let the last root remain.
        from app.modules.auth.models import User as UserModel
        from sqlalchemy import func, select

        # Re-fetch inside count to avoid stale data.
        from app.core.db import session_scope as _scope
        async with _scope() as session:
            count = await session.execute(
                select(func.count()).select_from(UserModel).where(UserModel.role == ROLE_ROOT)
            )
            remaining = int(count.scalar_one() or 0)
        if remaining <= 1:
            raise HTTPException(
                status_code=400, detail="cannot delete the last remaining root user"
            )
    await service.delete_user(user_id)
    return {"status": "ok"}


@router.patch("/users/{user_id}/password")
async def change_password(
    user_id: UUID,
    payload: ChangePasswordRequest,
    current: Annotated[User, Depends(get_current_user)],
) -> dict:
    if current.role != ROLE_ROOT and current.id != user_id:
        raise HTTPException(status_code=403, detail="can only change your own password")
    if current.id == user_id and current.role == ROLE_ROOT:
        # root can change own password freely
        pass
    try:
        await service.change_password(user_id, payload.new_password)
    except service.AuthError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok"}
