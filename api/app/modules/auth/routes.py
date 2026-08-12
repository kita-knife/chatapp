"""Auth API routes: login, logout, me."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.core.config import settings
from app.modules.auth import service
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthStatus(BaseModel):
    authenticated: bool
    user: dict | None = None


@router.get("/status", response_model=AuthStatus)
async def status_endpoint(
    current: Annotated[User | None, Depends(get_current_user)] = None,
) -> AuthStatus:
    user_dict = None
    if current:
        from app.modules.users_prefs import service as prefs_service

        user_dict = {
            "id": str(current.id),
            "username": current.username,
            "role": current.role,
            "preferences": await prefs_service.get_preferences(current.id),
        }
    return AuthStatus(authenticated=current is not None, user=user_dict)


@router.post("/login", response_model=AuthStatus)
async def login_endpoint(payload: LoginRequest, response: Response) -> AuthStatus:
    try:
        user = await service.authenticate(payload.username, payload.password)
    except service.InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    db_session = await service.create_session(user.id)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=db_session.token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return AuthStatus(
        authenticated=True,
        user={"id": str(user.id), "username": user.username, "role": user.role},
    )


@router.post("/logout")
async def logout_endpoint(
    response: Response,
    session_cookie: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> dict[str, str]:
    if session_cookie:
        await service.delete_session(session_cookie)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return {"status": "ok"}


@router.get("/me", response_model=dict)
async def me_endpoint(current: Annotated[User, Depends(get_current_user)]) -> dict:
    from app.modules.users_prefs import service as prefs_service

    return {
        "id": str(current.id),
        "username": current.username,
        "role": current.role,
        "created_at": current.created_at.isoformat(),
        "last_login_at": current.last_login_at.isoformat() if current.last_login_at else None,
        "preferences": await prefs_service.get_preferences(current.id),
    }
