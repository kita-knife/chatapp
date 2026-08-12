"""Auth business logic: users, sessions, role enforcement."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.db import session_scope
from app.core.security import hash_password, new_session_token, verify_password
from app.modules.auth.models import ROLE_ROOT, User
from app.modules.auth.session_model import AuthSession


class AuthError(Exception):
    """Generic auth error."""


class UsernameTakenError(AuthError):
    pass


class InvalidCredentialsError(AuthError):
    pass


class RootLimitReachedError(AuthError):
    pass


# ---------------- queries ----------------

async def get_user_by_username(username: str) -> User | None:
    async with session_scope() as session:
        result = await session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()


async def get_user_by_id(user_id: UUID) -> User | None:
    async with session_scope() as session:
        return await session.get(User, user_id)


async def list_users() -> list[User]:
    async with session_scope() as session:
        result = await session.execute(select(User).order_by(User.created_at.asc()))
        return list(result.scalars().all())


async def count_root_users() -> int:
    async with session_scope() as session:
        result = await session.execute(
            select(func.count()).select_from(User).where(User.role == ROLE_ROOT)
        )
        return int(result.scalar_one() or 0)


# ---------------- mutations ----------------

async def create_user(username: str, password: str, role: str = "user") -> User:
    if role == ROLE_ROOT:
        # Enforce the MAX_ROOT_USERS cap.
        current = await count_root_users()
        if current >= settings.max_root_users:
            raise RootLimitReachedError(
                f"max root users reached ({current}/{settings.max_root_users}). "
                f"Adjust MAX_ROOT_USERS to raise the limit."
            )

    existing = await get_user_by_username(username)
    if existing is not None:
        raise UsernameTakenError(f"username '{username}' already exists")

    async with session_scope() as session:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
        )
        session.add(user)
        await session.flush()
        await session.refresh(user)
        return user


async def delete_user(user_id: UUID) -> None:
    async with session_scope() as session:
        user = await session.get(User, user_id)
        if user is None:
            return
        # Explicitly invalidate all sessions for this user. The FK on
        # auth_sessions.user_id also has ON DELETE CASCADE, so this is
        # technically redundant — but it (a) matches the pattern in
        # `change_password` above for consistency, (b) survives if a future
        # migration ever drops the cascade, and (c) makes the intent
        # explicit in code without requiring readers to inspect the schema.
        await session.execute(
            delete(AuthSession).where(AuthSession.user_id == user_id)
        )
        await session.delete(user)


async def change_password(user_id: UUID, new_password: str) -> None:
    async with session_scope() as session:
        user = await session.get(User, user_id)
        if user is None:
            raise AuthError("user not found")
        user.password_hash = hash_password(new_password)
        # Invalidate all existing sessions for this user, including the one
        # that initiated this change. The user will need to log in again
        # with the new password (already in hand, since they just typed it).
        # This prevents a stolen cookie from remaining valid after a password
        # change — both for the affected user and for any other device that
        # happened to be logged in.
        await session.execute(
            delete(AuthSession).where(AuthSession.user_id == user_id)
        )


# ---------------- sessions ----------------

async def authenticate(username: str, password: str) -> User:
    user = await get_user_by_username(username)
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError("invalid username or password")
    return user


async def create_session(user_id: UUID) -> AuthSession:
    token = new_session_token()
    expires = datetime.now(timezone.utc) + timedelta(seconds=settings.session_ttl_seconds)
    async with session_scope() as session:
        db_session = AuthSession(user_id=user_id, token=token, expires_at=expires)
        session.add(db_session)
        await session.flush()
        await session.refresh(db_session)
        # Update last_login_at too.
        from sqlalchemy import update

        await session.execute(
            update(User).where(User.id == user_id).values(last_login_at=datetime.now(timezone.utc))
        )
        return db_session


async def get_session_by_token(token: str) -> AuthSession | None:
    async with session_scope() as session:
        result = await session.execute(select(AuthSession).where(AuthSession.token == token))
        db_session = result.scalar_one_or_none()
        if db_session is None:
            return None
        if db_session.expires_at < datetime.now(timezone.utc):
            return None
        return db_session


async def delete_session(token: str) -> None:
    async with session_scope() as session:
        result = await session.execute(
            select(AuthSession).where(AuthSession.token == token)
        )
        db_session = result.scalar_one_or_none()
        if db_session is not None:
            await session.delete(db_session)
