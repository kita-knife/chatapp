"""ChatApp-PG FastAPI entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.db import dispose_engine, init_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("starting (env=%s)", settings.app_env)
    # Install upstream-agno compatibility patches (idempotent). Must run
    # before any agent/model construction.
    from app.core.agno_compat import apply_agno_patches

    apply_agno_patches()
    init_engine()
    # Initialize the agno Agent DB (lazily creates its `agno` schema tables
    # on first session access). Shares the app engine — no separate pool.
    from app.core.agno_db import get_agno_db

    get_agno_db()
    try:
        yield
    finally:
        await dispose_engine()
        logger.info("shutdown_complete")


app = FastAPI(
    title="ChatApp-PG",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_base_url, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": "ChatApp-PG", "version": "0.2.0"}
