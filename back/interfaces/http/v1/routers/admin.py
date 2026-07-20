"""Admin and operator API router group."""

from fastapi import APIRouter, Depends

from SafeMealAgent.back.interfaces.http.v1.endpoints.knowledge import router as knowledge_router
from SafeMealAgent.back.interfaces.http.v1.endpoints.sources import router as sources_router
from SafeMealAgent.back.interfaces.http.v1.endpoints.upload import router as upload_router
from SafeMealAgent.back.interfaces.http.security import require_admin

admin_api_router = APIRouter(dependencies=[Depends(require_admin)])
admin_api_router.include_router(knowledge_router)
admin_api_router.include_router(sources_router)
admin_api_router.include_router(upload_router, prefix="/upload", tags=["File Upload"])

__all__ = ["admin_api_router"]
