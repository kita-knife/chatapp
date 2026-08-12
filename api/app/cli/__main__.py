"""CLI entry point: `uv run python -m app.cli <subcommand> [...]`."""
from __future__ import annotations

import argparse
import asyncio
import sys

from app.core.config import settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="chatapp-cli", description="ChatApp-PG admin CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_root = sub.add_parser("create-root", help="Create a root user")
    p_root.add_argument("--username", help="username (non-interactive)")
    p_root.add_argument(
        "--password",
        help=(
            f"password (non-interactive; >= {settings.root_password_min_len} chars)"
        ),
    )

    args = parser.parse_args()
    if args.cmd == "create-root":
        from app.cli.create_root import run

        sys.exit(asyncio.run(run(args.username, args.password)))


main()
