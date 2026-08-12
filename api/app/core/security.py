"""Security primitives: password hashing, session signing.

Uses the `bcrypt` package directly (no passlib). Passlib 1.7.4 is unmaintained
and produces a noisy "bcrypt version" warning on every hash call.
"""
from __future__ import annotations

import secrets

import bcrypt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed hash, wrong scheme, etc. — treat as auth failure.
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)
