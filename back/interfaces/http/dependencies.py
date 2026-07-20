"""HTTP 依赖装配。

本模块是 FastAPI 接口层的依赖入口，只负责把请求绑定到组合根或服务客户端，
不承载业务规则。
"""

from fastapi import Depends, Request

from SafeMealAgent.back.application.use_cases.agent.graph_runner_service import (
    AgentGraphRunnerService,
)
from SafeMealAgent.back.application.use_cases.agent.internal_process_service import (
    InternalAgentProcessService,
)
from SafeMealAgent.back.application.use_cases.agent.context_builder import AgentContextBuilder
from SafeMealAgent.back.application.use_cases.agent.conversation_memory import (
    ConversationMemoryManager,
    MemoryRelevanceSelector,
)
from SafeMealAgent.back.application.use_cases.agent.context_registry import (
    create_default_agent_context_providers,
)
from SafeMealAgent.back.application.use_cases.chat.persistence_service import ChatPersistenceService
from SafeMealAgent.back.application.use_cases.chat.session_management_service import (
    SessionManagementService,
)
from SafeMealAgent.back.application.use_cases.chat.turn_service import ChatTurnService
from SafeMealAgent.back.application.use_cases.feedback.service import AnswerFeedbackService
from SafeMealAgent.back.application.use_cases.knowledge.service import KnowledgeService
from SafeMealAgent.back.application.use_cases.knowledge.lightrag_service import (
    LightRAGApplicationService,
)
from SafeMealAgent.back.application.use_cases.knowledge.recipe_service import RecipeKnowledgeService
from SafeMealAgent.back.application.use_cases.memory.user_memory_service import UserMemoryService
from SafeMealAgent.back.application.use_cases.upload.service import UploadService
from SafeMealAgent.back.bootstrap import AppContainer
from SafeMealAgent.back.infrastructure.retrieval.neo4j.service import Neo4jGraphService
from SafeMealAgent.back.infrastructure.retrieval.lightrag.service import LightRAGService
from SafeMealAgent.back.infrastructure.ingestion.sync import SourceSyncService
from SafeMealAgent.back.infrastructure.ingestion.documents import DocumentParserRegistry
from SafeMealAgent.back.infrastructure.persistence.chat_repository import sqlalchemy_chat_unit_of_work
from SafeMealAgent.back.infrastructure.persistence.feedback_repository import (
    sqlalchemy_answer_feedback_repository,
)
from SafeMealAgent.back.infrastructure.persistence.user_memory_repository import (
    sqlalchemy_user_memory_unit_of_work,
)
from SafeMealAgent.back.config.settings import settings
from SafeMealAgent.back.shared.contracts.feedback import FailureCollector
from SafeMealAgent.back.shared.contracts.memory import AgentMemoryProvider
from SafeMealAgent.back.application.observability.store import AgentTraceStore


def get_container(request: Request) -> AppContainer:
    """Return the process container attached during application creation."""

    return request.app.state.container


def get_online_failure_collector(
    container: AppContainer = Depends(get_container),
) -> FailureCollector:
    return container.failure_collector


def get_agent_trace_store(
    container: AppContainer = Depends(get_container),
) -> AgentTraceStore:
    return container.trace_store


def get_agent_graph_runner_service(
    container: AppContainer = Depends(get_container),
) -> AgentGraphRunnerService:
    return container.get_agent_graph_runner_service()


def get_chat_persistence() -> ChatPersistenceService:
    return ChatPersistenceService(
        uow_factory=sqlalchemy_chat_unit_of_work,
        history_messages=settings.AGENT_HISTORY_SCAN_MESSAGES,
        processing_timeout_seconds=settings.AGENT_TIMEOUT + 60,
    )


def get_session_management() -> SessionManagementService:
    return SessionManagementService(uow_factory=sqlalchemy_chat_unit_of_work)


def get_answer_feedback_service(
    session_management: SessionManagementService = Depends(get_session_management),
    collector: FailureCollector = Depends(get_online_failure_collector),
) -> AnswerFeedbackService:
    return AnswerFeedbackService(
        session_management=session_management,
        repository=sqlalchemy_answer_feedback_repository(),
        collector=collector,
    )


def get_agent_memory_provider() -> AgentMemoryProvider:
    """返回 Agent 主链路使用的本地记忆能力。

    Memory 是每轮对话的高频上下文能力，默认随主应用本地部署，不走 HTTP。
    """

    return UserMemoryService(uow_factory=sqlalchemy_user_memory_unit_of_work)


def get_user_memory_service() -> UserMemoryService:
    """返回本地用户长期记忆用例，供主 API 的 memories 路由使用。"""

    return UserMemoryService(uow_factory=sqlalchemy_user_memory_unit_of_work)


def get_agent_context_builder(
    memory_service: AgentMemoryProvider = Depends(get_agent_memory_provider),
) -> AgentContextBuilder:
    return AgentContextBuilder(
        providers=create_default_agent_context_providers(
            memory_provider=memory_service,
            memory_limit=settings.AGENT_MEMORY_RETRIEVAL_LIMIT,
        ),
        conversation_manager=ConversationMemoryManager(
            token_budget=settings.AGENT_CONTEXT_TOKEN_BUDGET,
            response_token_reserve=settings.AGENT_RESPONSE_TOKEN_RESERVE,
        ),
    )


def get_chat_turn_service(
    persistence: ChatPersistenceService = Depends(get_chat_persistence),
    agent_service: AgentGraphRunnerService = Depends(get_agent_graph_runner_service),
    context_builder: AgentContextBuilder = Depends(get_agent_context_builder),
) -> ChatTurnService:
    """装配一轮 Chat 用例。

    HTTP Router 不再直接串联 Agent、Memory、Persistence，而是只依赖该用例服务。
    """

    return ChatTurnService(
        persistence=persistence,
        agent_processor=agent_service,
        context_builder=context_builder,
    )


def get_agent_process_service(
    container: AppContainer = Depends(get_container),
    agent_service: AgentGraphRunnerService = Depends(get_agent_graph_runner_service),
    memory_service: AgentMemoryProvider = Depends(get_agent_memory_provider),
) -> InternalAgentProcessService:
    """装配服务间 Agent 调用用例。"""

    return InternalAgentProcessService(
        agent_processor=agent_service,
        memory_provider=memory_service,
        conversation_manager=ConversationMemoryManager(
            token_budget=settings.AGENT_CONTEXT_TOKEN_BUDGET,
            response_token_reserve=settings.AGENT_RESPONSE_TOKEN_RESERVE,
        ),
        memory_selector=MemoryRelevanceSelector(
            limit=settings.AGENT_MEMORY_RETRIEVAL_LIMIT
        ),
    )


async def get_knowledge_service(
    container: AppContainer = Depends(get_container),
) -> KnowledgeService:
    return await container.get_knowledge_service()


async def get_recipe_knowledge_service(
    knowledge_service: KnowledgeService = Depends(get_knowledge_service),
) -> RecipeKnowledgeService:
    return RecipeKnowledgeService(knowledge_service)


def get_neo4j_graph_service(
    container: AppContainer = Depends(get_container),
) -> Neo4jGraphService:
    return container.get_neo4j_graph_service()


def get_lightrag_service(
    container: AppContainer = Depends(get_container),
) -> LightRAGService:
    return container.get_lightrag_service()


def get_lightrag_application_service(
    gateway: LightRAGService = Depends(get_lightrag_service),
) -> LightRAGApplicationService:
    return LightRAGApplicationService(gateway)


def get_upload_service(
    container: AppContainer = Depends(get_container),
) -> UploadService:
    return container.upload_service


def get_document_parser_registry(
    container: AppContainer = Depends(get_container),
) -> DocumentParserRegistry:
    return container.document_parsers


async def get_source_sync_service(
    container: AppContainer = Depends(get_container),
) -> SourceSyncService:
    return await container.get_source_sync_service()
