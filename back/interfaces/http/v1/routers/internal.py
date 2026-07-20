"""Internal service and implementation-detail API router group."""

from fastapi import APIRouter, Depends

from SafeMealAgent.back.interfaces.http.v1.endpoints.agent import router as agent_router
from SafeMealAgent.back.interfaces.http.v1.endpoints.integrations import router as integrations_router
from SafeMealAgent.back.interfaces.http.v1.endpoints.lightrag import router as lightrag_router
from SafeMealAgent.back.interfaces.http.v1.endpoints.runtime_observability import (
    router as runtime_observability_router,
)
from SafeMealAgent.back.interfaces.http.security import require_internal

internal_api_router = APIRouter(dependencies=[Depends(require_internal)])
internal_api_router.include_router(
    agent_router, prefix="/agent", tags=["Agent Orchestrator"]
)
internal_api_router.include_router(integrations_router)
internal_api_router.include_router(lightrag_router)
internal_api_router.include_router(runtime_observability_router)

__all__ = ["internal_api_router"]
