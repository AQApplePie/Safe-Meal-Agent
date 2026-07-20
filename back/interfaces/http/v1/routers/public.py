"""Public user-facing API router group."""

from fastapi import APIRouter, Depends

from SafeMealAgent.back.interfaces.http.v1.endpoints.chat import router as chat_router
from SafeMealAgent.back.interfaces.http.v1.endpoints.feedback import router as feedback_router
from SafeMealAgent.back.interfaces.http.v1.endpoints.memories import router as memories_router
from SafeMealAgent.back.interfaces.http.v1.endpoints.sessions import router as sessions_router
from SafeMealAgent.back.interfaces.http.security import require_authenticated

public_api_router = APIRouter(dependencies=[Depends(require_authenticated)])
public_api_router.include_router(
    sessions_router, prefix="/sessions", tags=["Chat Sessions"]
)
public_api_router.include_router(chat_router, prefix="/chat", tags=["Unified Chat"])
public_api_router.include_router(
    memories_router, prefix="/memories", tags=["User Memories"]
)
public_api_router.include_router(
    feedback_router,
    prefix="/feedback",
    tags=["Answer Feedback"],
)

__all__ = ["public_api_router"]
