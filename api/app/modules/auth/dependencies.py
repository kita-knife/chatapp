"""Auth dependencies: current user resolution + role enforcement."""
from __future__ import annotations

from typing import Annotated, Iterable

from fastapi import Cookie, Depends, HTTPException, status

from app.core.config import settings
from app.modules.auth import service
from app.modules.auth.models import User


async def get_current_user(
    session_cookie: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> User:
    """Resolve the current user from the session cookie. Raises 401 if invalid."""
    if session_cookie is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    db_session = await service.get_session_by_token(session_cookie)
    if db_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session")
    user = await service.get_user_by_id(db_session.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user missing")
    return user


def require_role(*roles: str):
    """FastAPI dependency factory that enforces role membership."""
    allowed = frozenset(roles)

    async def dependency(
        current: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if current.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires role: {sorted(allowed)}",
            )
        return current

    return dependency


async def get_optional_user(
    session_cookie: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> User | None:
    if session_cookie is None:
        return None
    db_session = await service.get_session_by_token(session_cookie)
    if db_session is None:
        return None
    return await service.get_user_by_id(db_session.user_id)
