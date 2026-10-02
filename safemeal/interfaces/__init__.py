from fastapi import APIRouter

from safemeal.interfaces.http.routers.auth import router as auth_router
from safemeal.interfaces.http.routers.chat import router as chat_router
from safemeal.interfaces.http.routers.knowledge import router as knowledge_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_router.include_router(chat_router, prefix="/chat", tags=["Unified Chat"])
api_router.include_router(
    knowledge_router, prefix="/knowledge", tags=["File Knowledge"]
)

__all__ = ["api_router"]
