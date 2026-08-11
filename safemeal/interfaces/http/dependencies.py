"""HTTP 依赖装配。

本模块是 FastAPI 接口层的依赖入口，只负责把请求绑定到组合根或服务客户端，
不承载业务规则。
"""

from fastapi import Depends, Request

from safemeal.application.agent.execution_service import (
    AgentExecutionService,
)
from safemeal.application.agent.request_service import (
    AgentRequestService,
)
from safemeal.application.agent.context.builder import AgentContextBuilder
from safemeal.application.use_cases.chat.turn_persistence import (
    ChatTurnPersistence,
)
from safemeal.application.use_cases.chat.chat_session_service import (
    ChatSessionService,
)
from safemeal.application.use_cases.chat.chat_turn_service import ChatTurnService
from safemeal.application.use_cases.knowledge.document_knowledge_service import (
    DocumentKnowledgeService,
)
from safemeal.application.use_cases.knowledge.recipe_indexing import (
    RecipeDocumentIndexer,
)
from safemeal.application.use_cases.memory.user_memory_service import UserMemoryService
from safemeal.application.use_cases.upload.file_upload_service import FileUploadService
from safemeal.application.use_cases.upload.uploaded_document_ingestion_service import (
    UploadedDocumentIngestionService,
)
from safemeal.bootstrap import ApplicationContainer
from safemeal.application.observability.store import AgentTraceStore


def get_container(request: Request) -> ApplicationContainer:
    """Return the process container attached during application creation."""

    return request.app.state.container


def get_agent_trace_store(
    container: ApplicationContainer = Depends(get_container),
) -> AgentTraceStore:
    return container.trace_store


def get_agent_execution_service(
    container: ApplicationContainer = Depends(get_container),
) -> AgentExecutionService:
    return container.get_agent_execution_service()


def get_chat_turn_persistence(
    container: ApplicationContainer = Depends(get_container),
) -> ChatTurnPersistence:
    return container.get_chat_turn_persistence()


def get_chat_session_service(
    container: ApplicationContainer = Depends(get_container),
) -> ChatSessionService:
    return container.get_chat_session_service()


def get_user_memory_service(
    container: ApplicationContainer = Depends(get_container),
) -> UserMemoryService:
    """返回本地用户长期记忆用例，供主 API 的 memories 路由使用。"""

    return container.get_user_memory_service()


def get_agent_context_builder(
    container: ApplicationContainer = Depends(get_container),
) -> AgentContextBuilder:
    return container.get_agent_context_builder()


def get_chat_turn_service(
    container: ApplicationContainer = Depends(get_container),
) -> ChatTurnService:
    """装配一轮 Chat 用例。

    HTTP Router 不再直接串联 Agent、Memory、Persistence，而是只依赖该用例服务。
    """

    return container.get_chat_turn_service()


def get_agent_request_service(
    container: ApplicationContainer = Depends(get_container),
) -> AgentRequestService:
    """装配服务间 Agent 调用用例。"""

    return container.get_agent_request_service()


async def get_document_knowledge_service(
    container: ApplicationContainer = Depends(get_container),
) -> DocumentKnowledgeService:
    return await container.get_document_knowledge_service()


async def get_recipe_document_indexer(
    container: ApplicationContainer = Depends(get_container),
) -> RecipeDocumentIndexer:
    return await container.get_recipe_document_indexer()


def get_file_upload_service(
    container: ApplicationContainer = Depends(get_container),
) -> FileUploadService:
    return container.file_upload_service


async def get_uploaded_document_ingestion_service(
    container: ApplicationContainer = Depends(get_container),
) -> UploadedDocumentIngestionService:
    return await container.get_uploaded_document_ingestion_service()
