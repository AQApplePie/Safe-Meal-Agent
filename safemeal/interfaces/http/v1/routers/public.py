"""Public user-facing API router group."""

from fastapi import APIRouter, Depends

from safemeal.interfaces.http.v1.endpoints.chat import router as chat_router
from safemeal.interfaces.http.v1.endpoints.memories import router as memories_router
from safemeal.interfaces.http.v1.endpoints.sessions import router as sessions_router
from safemeal.interfaces.http.security import require_authenticated

public_api_router = APIRouter(dependencies=[Depends(require_authenticated)])
public_api_router.include_router(
    sessions_router, prefix="/sessions", tags=["Chat Sessions"]
)
public_api_router.include_router(chat_router, prefix="/chat", tags=["Unified Chat"])
public_api_router.include_router(
    memories_router, prefix="/memories", tags=["User Memories"]
)

__all__ = ["public_api_router"]
