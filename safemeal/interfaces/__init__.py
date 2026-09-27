from fastapi import APIRouter, Depends

from safemeal.interfaces.http.authentication import get_current_principal
from safemeal.interfaces.http.authentication import (  # noqa: F401
    Principal,
    authorize_user_id,
)
from safemeal.interfaces.http.answer_stream import stream_answer_events  # noqa: F401
from safemeal.interfaces.http.dependencies import (  # noqa: F401
    get_agent_trace_store,
    get_chat_session_service,
    get_chat_turn_service,
    get_document_knowledge_service,
    get_file_upload_service,
    get_recipe_document_indexer,
    get_uploaded_document_ingestion_service,
    get_user_memory_service,
)
from safemeal.interfaces.http.models import *  # noqa: F403

from safemeal.interfaces.http.routers.agent import router as agent_router
from safemeal.interfaces.http.routers.agent_traces import router as agent_traces_router
from safemeal.interfaces.http.routers.chat import router as chat_router
from safemeal.interfaces.http.routers.integrations import router as integrations_router
from safemeal.interfaces.http.routers.knowledge import router as knowledge_router
from safemeal.interfaces.http.routers.memories import router as memories_router
from safemeal.interfaces.http.routers.sessions import router as sessions_router
from safemeal.interfaces.http.routers.upload import router as upload_router

api_router = APIRouter(dependencies=[Depends(get_current_principal)])
api_router.include_router(sessions_router, prefix="/sessions", tags=["Chat Sessions"])
api_router.include_router(chat_router, prefix="/chat", tags=["Unified Chat"])
api_router.include_router(memories_router, prefix="/memories", tags=["User Memories"])
api_router.include_router(knowledge_router)
api_router.include_router(upload_router, prefix="/upload", tags=["File Upload"])
api_router.include_router(agent_router, prefix="/agent", tags=["Agent Orchestrator"])
api_router.include_router(integrations_router)
api_router.include_router(agent_traces_router)

__all__ = ["api_router"]
