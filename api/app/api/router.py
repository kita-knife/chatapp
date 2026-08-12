"""API v1 router."""
from __future__ import annotations

from fastapi import APIRouter

from app.modules.auth.routes import router as auth_router
from app.modules.auth.users.routes import router as users_router
from app.modules.chat.routes import router as chat_router
from app.modules.users_prefs.routes import router as prefs_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(users_router, prefix="/auth", tags=["users"])
api_router.include_router(prefs_router, prefix="/auth", tags=["preferences"])
api_router.include_router(chat_router, prefix="/chat", tags=["chat"])


@api_router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
