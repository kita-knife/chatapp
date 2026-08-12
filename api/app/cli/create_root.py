"""create-root subcommand.

Usage:
  uv run python -m app.cli create-root
  uv run python -m app.cli create-root --username admin --password 'secret'
"""
from __future__ import annotations

import getpass
import sys

from app.core.config import settings
from app.core.db import dispose_engine, init_engine
from app.core.logging import configure_logging
from app.modules.auth import service
from app.modules.auth.models import ROLE_ROOT

configure_logging("info")


def _err(s: str) -> int:
    print(f"ERROR: {s}", file=sys.stderr)
    return 2


async def run(username: str | None, password: str | None) -> int:
    init_engine()

    # 1. Verify the MAX_ROOT_USERS cap.
    current = await service.count_root_users()
    if current >= settings.max_root_users:
        await dispose_engine()
        return _err(
            f"max root users reached ({current}/{settings.max_root_users}). "
            f"Adjust MAX_ROOT_USERS to raise the limit."
        )

    # 2. Username resolution
    if username is None:
        for _ in range(3):
            username = input("username: ").strip()
            if len(username) >= settings.root_username_min_len:
                break
            print(
                f"username must be at least {settings.root_username_min_len} characters",
                file=sys.stderr,
            )
        else:
            await dispose_engine()
            return _err("username too short (3 attempts)")
    if len(username) < settings.root_username_min_len:
        await dispose_engine()
        return _err(
            f"username must be at least {settings.root_username_min_len} characters"
        )

    # 3. Password resolution
    if password is None:
        for _ in range(3):
            password = getpass.getpass("password: ")
            if len(password) >= settings.root_password_min_len:
                confirm = getpass.getpass("confirm: ")
                if password != confirm:
                    print("passwords do not match", file=sys.stderr)
                    continue
                break
            print(
                f"password must be at least {settings.root_password_min_len} characters",
                file=sys.stderr,
            )
        else:
            await dispose_engine()
            return _err("password too short (3 attempts)")
    if len(password) < settings.root_password_min_len:
        await dispose_engine()
        return _err(
            f"password must be at least {settings.root_password_min_len} characters"
        )

    # 4. Create
    try:
        user = await service.create_user(username, password, ROLE_ROOT)
    except service.UsernameTakenError as exc:
        await dispose_engine()
        return _err(str(exc))
    except service.RootLimitReachedError as exc:
        await dispose_engine()
        return _err(str(exc))

    new_count = await service.count_root_users()
    await dispose_engine()
    print(f"✓ root user '{user.username}' created ({new_count}/{settings.max_root_users})")
    return 0
