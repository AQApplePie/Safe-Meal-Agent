"""Central ownership of application services and external resources."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
from threading import RLock
from typing import Optional

from safemeal.application.service.composition.model_factory import (
    create_language_model_gateway,
)
from safemeal.application.agent.orchestration import build_agent_graph
from safemeal.application.workflow.graph import (
    build_chat_workflow,
    build_resume_workflow,
)
from safemeal.application.workflow.runner import ChatWorkflow
from safemeal.application.service.composition.dietary_search_factory import (
    create_dietary_search,
)
from safemeal.application.workflow.context.builder import (
    AgentContextBuilder,
    create_default_agent_context_providers,
)
from safemeal.application.workflow.context.conversation_context import (
    ConversationContextWindow,
)
from safemeal.application.runtime_budget import parse_model_pricing
from safemeal.application.ports.tools.tool_executor import ToolExecutor
from safemeal.application.ports.ingestion.ingestion_queue import IngestionQueue
from safemeal.application.exceptions import FeatureUnavailableError
from safemeal.application.agent.gateway import (
    AgentExecutionService,
)
from safemeal.application.service.chat.chat_turn_service import ChatTurnService
from safemeal.application.service.chat.chat_session_service import ChatSessionService
from safemeal.application.service.chat.turn_persistence import ChatTurnPersistence
from safemeal.application.service.chat.conversation_history_service import (
    ConversationHistoryService,
)
from safemeal.application.service.knowledge.document_knowledge_service import (
    DocumentKnowledgeService,
)
from safemeal.application.service.memory.user_memory_service import UserMemoryService
from safemeal.application.service.auth import AuthService
from safemeal.application.service.recipes import (
    RecipeService,
)
from safemeal.application.service.upload.file_upload_service import FileUploadService
from safemeal.application.service.upload.uploaded_document_ingestion_service import (
    UploadedDocumentIngestionService,
)
from safemeal.config.settings import settings
from safemeal.application.service.composition.document_knowledge_factory import (
    create_document_knowledge_service_async,
)
from safemeal.infrastructure.llm.openai_language_model_gateway import (
    OpenAILanguageModelGateway,
)
from safemeal.application.agent.tools import build_tool_executor, LocalToolExecutor
from safemeal.infrastructure.ingestion.document_parser import DocumentParserRegistry
from safemeal.infrastructure.ingestion.local_upload_storage import LocalUploadStorage
from safemeal.infrastructure.ingestion.redis_queue import RedisIngestionQueue
from safemeal.infrastructure.persistence.database import (
    dispose_engine,
    configure_database,
)
from safemeal.infrastructure.persistence.threaded_checkpoint import (
    ThreadedCheckpointSaver,
)
from safemeal.infrastructure.persistence.checkpoint_serializer import (
    ContractCheckpointSerializer,
)
from safemeal.infrastructure.persistence.langgraph_checkpoint import (
    SqliteCheckpointSaver,
)
from safemeal.infrastructure.persistence.recipe_repository import (
    SqlAlchemyRecipeRepository,
)
from safemeal.infrastructure.retrieval.local_recipe_catalog import (
    LocalRecipeDocumentCatalog,
)
from safemeal.infrastructure.retrieval.wikibooks_recipe_provider import (
    WikibooksRecipeProvider,
)
from safemeal.infrastructure.nlu.local_request_understanding import (
    LocalModelRequestUnderstandingGateway,
)
from safemeal.application.service.chat.request_understanding import (
    RuleBasedRequestUnderstandingGateway,
)
from safemeal.infrastructure.persistence.chat_repository import (
    sqlalchemy_chat_unit_of_work,
)
from safemeal.infrastructure.persistence.user_memory_repository import (
    sqlalchemy_user_memory_unit_of_work,
)
from safemeal.infrastructure.persistence.auth_repository import (
    sqlalchemy_auth_unit_of_work,
)
from safemeal.infrastructure.security import Argon2PasswordHasher, JwtTokenIssuer


class ApplicationContainer:
    """Own process-scoped application services and external resources."""

    def __init__(self) -> None:
        configure_database(
            settings.DATABASE_URL,
            debug=settings.DEBUG,
            connect_timeout=settings.DB_CONNECT_TIMEOUT,
        )
        self._document_knowledge_service: Optional[DocumentKnowledgeService] = None
        self._document_knowledge_lock = asyncio.Lock()
        self._singleton_lock = RLock()
        self._agent_execution_service: Optional[AgentExecutionService] = None
        self._tool_executor: Optional[LocalToolExecutor] = None
        self._recipe_service: Optional[RecipeService] = None
        self._language_model_gateway: Optional[OpenAILanguageModelGateway] = None
        self._auth_service: Optional[AuthService] = None
        self._document_parsers = DocumentParserRegistry()
        self._file_upload_service = FileUploadService(
            storage=LocalUploadStorage(settings.UPLOAD_DIR),
            max_size_bytes=settings.FILE_UPLOAD_MAX_MB * 1024 * 1024,
        )
        self._resource_stack = ExitStack()
        if settings.AGENT_CHECKPOINT_DATABASE_URL:
            from langgraph.checkpoint.postgres import PostgresSaver

            self._checkpointer = self._resource_stack.enter_context(
                PostgresSaver.from_conn_string(settings.AGENT_CHECKPOINT_DATABASE_URL)
            )
            self._checkpointer.serde = ContractCheckpointSerializer()
            self._checkpointer.setup()
            self._checkpointer = ThreadedCheckpointSaver(self._checkpointer)
        else:
            self._checkpointer = SqliteCheckpointSaver(
                settings.AGENT_CHECKPOINT_PATH, serde=ContractCheckpointSerializer()
            )
        self._ingestion_queue = (
            RedisIngestionQueue(
                settings.INGESTION_QUEUE_URL,
                queue_name=settings.INGESTION_QUEUE_NAME,
                ttl_seconds=settings.INGESTION_JOB_TTL_SECONDS,
            )
            if settings.INGESTION_QUEUE_URL
            else None
        )

    async def get_document_knowledge_service(self) -> DocumentKnowledgeService:
        """Return the shared Milvus service, creating it off the event loop."""

        if not (settings.ENABLE_MILVUS and settings.ENABLE_EMBEDDINGS):
            raise FeatureUnavailableError("Vector knowledge search is disabled")

        if self._document_knowledge_service is None:
            async with self._document_knowledge_lock:
                if self._document_knowledge_service is None:
                    self._document_knowledge_service = (
                        await create_document_knowledge_service_async()
                    )
        return self._document_knowledge_service

    def get_recipe_service(self) -> RecipeService:
        """Return the process-scoped structured recipe application service."""

        if self._recipe_service is None:
            with self._singleton_lock:
                if self._recipe_service is None:
                    providers = [
                        LocalRecipeDocumentCatalog(settings.NEO4J_RECIPE_JSON_PATH)
                    ]
                    if settings.ENABLE_EXTERNAL_RECIPE_SEARCH:
                        providers.append(
                            WikibooksRecipeProvider(
                                endpoint=settings.EXTERNAL_RECIPE_ENDPOINT,
                                timeout_seconds=settings.EXTERNAL_RECIPE_TIMEOUT,
                            )
                        )
                    self._recipe_service = RecipeService(
                        SqlAlchemyRecipeRepository(),
                        model_gateway=self.get_language_model_gateway()
                        if settings.ENABLE_LLM
                        else None,
                        lookup_providers=tuple(providers),
                    )
        return self._recipe_service

    def get_language_model_gateway(self) -> OpenAILanguageModelGateway:
        """Return the single production model adapter used by Agent and generation."""

        if self._language_model_gateway is None:
            with self._singleton_lock:
                if self._language_model_gateway is None:
                    self._language_model_gateway = create_language_model_gateway()
        return self._language_model_gateway

    def get_tool_executor(self) -> LocalToolExecutor:
        """Return the process-scoped local tools executor."""

        if self._tool_executor is None:
            with self._singleton_lock:
                if self._tool_executor is None:
                    enabled_tools = {
                        "search_recipes",
                        "get_recipe",
                        "recommend_recipes",
                        "generate_recipe",
                    }
                    if settings.ENABLE_MILVUS and settings.ENABLE_EMBEDDINGS:
                        enabled_tools.add("milvus_vector_search")
                    if settings.ENABLE_NEO4J:
                        enabled_tools.add("dietary_safe_recipe_query")
                    self._tool_executor = build_tool_executor(
                        document_knowledge_provider=self.get_document_knowledge_service,
                        recipe_service=self.get_recipe_service(),
                        enabled_tools=enabled_tools,
                        timeout_seconds=settings.AGENT_TOOL_TIMEOUT,
                        dietary_search=create_dietary_search()
                        if settings.ENABLE_NEO4J
                        else None,
                    )
        return self._tool_executor

    def get_agent_execution_service(self) -> AgentExecutionService:
        """组装包含请求策略和 LangGraph 执行的本地 Agent 服务。

        默认运行形态是模块化单体：Agent、Memory、Tool 都在主进程内本地调用，
        避免高频主链路多次 HTTP 跳转。
        """

        if self._agent_execution_service is None:
            with self._singleton_lock:
                if self._agent_execution_service is None:
                    self._agent_execution_service = (
                        self._create_agent_execution_service(
                            model_gateway=(
                                self.get_language_model_gateway()
                                if settings.ENABLE_LLM
                                else None
                            ),
                            tool_executor=(
                                self.get_tool_executor()
                                if settings.ENABLE_LLM
                                else None
                            ),
                        )
                    )
        return self._agent_execution_service

    def get_chat_turn_persistence(self) -> ChatTurnPersistence:
        """Build chat-turn persistence with the production SQLAlchemy UoW."""

        return ChatTurnPersistence(
            uow_factory=sqlalchemy_chat_unit_of_work,
        )

    def get_chat_session_service(self) -> ChatSessionService:
        """Build session use cases with the production SQLAlchemy UoW."""

        return ChatSessionService(uow_factory=sqlalchemy_chat_unit_of_work)

    def get_user_memory_service(self) -> UserMemoryService:
        """Build user-memory use cases with the production SQLAlchemy UoW."""

        return UserMemoryService(uow_factory=sqlalchemy_user_memory_unit_of_work)

    def get_auth_service(self) -> AuthService:
        if self._auth_service is None:
            with self._singleton_lock:
                if self._auth_service is None:
                    self._auth_service = AuthService(
                        uow_factory=sqlalchemy_auth_unit_of_work,
                        password_hasher=Argon2PasswordHasher(),
                        token_issuer=JwtTokenIssuer(
                            secret=settings.AUTH_JWT_SECRET,
                            issuer=settings.AUTH_JWT_ISSUER,
                            audience=settings.AUTH_JWT_AUDIENCE,
                            access_token_minutes=settings.AUTH_ACCESS_TOKEN_MINUTES,
                        ),
                        refresh_token_days=settings.AUTH_REFRESH_TOKEN_DAYS,
                        default_tenant_id=settings.DEFAULT_TENANT_ID,
                    )
        return self._auth_service

    def get_agent_context_builder(self) -> AgentContextBuilder:
        """Build the production Agent context pipeline."""

        memory_service = self.get_user_memory_service()
        return AgentContextBuilder(
            history_service=ConversationHistoryService(
                sqlalchemy_chat_unit_of_work,
                history_messages=settings.AGENT_HISTORY_SCAN_MESSAGES,
            ),
            providers=create_default_agent_context_providers(
                memory_service=memory_service,
                memory_limit=settings.AGENT_MEMORY_RETRIEVAL_LIMIT,
            ),
            conversation_window=ConversationContextWindow(
                token_budget=settings.AGENT_CONTEXT_TOKEN_BUDGET,
                response_token_reserve=settings.AGENT_RESPONSE_TOKEN_RESERVE,
            ),
        )

    def get_chat_turn_service(self) -> ChatTurnService:
        """Build the complete application service for one persisted chat turn."""

        return ChatTurnService(
            persistence=self.get_chat_turn_persistence(),
            workflow=self.get_chat_workflow(),
        )

    def get_chat_workflow(self) -> ChatWorkflow:
        return ChatWorkflow(
            build_chat_workflow(
                agent=self.get_agent_execution_service(),
                context_builder=self.get_agent_context_builder(),
                memory_service=self.get_user_memory_service(),
                request_understanding_gateway=(
                    LocalModelRequestUnderstandingGateway(
                        settings.REQUEST_UNDERSTANDING_MODEL_PATH
                    )
                    if settings.REQUEST_UNDERSTANDING_BACKEND == "local_model"
                    else RuleBasedRequestUnderstandingGateway()
                ),
                request_understanding_confidence_threshold=(
                    settings.REQUEST_UNDERSTANDING_CONFIDENCE_THRESHOLD
                ),
            ),
            build_resume_workflow(agent=self.get_agent_execution_service()),
        )

    async def get_uploaded_document_ingestion_service(
        self,
    ) -> UploadedDocumentIngestionService:
        """Build the complete save, parse and knowledge-indexing use case."""

        return UploadedDocumentIngestionService(
            file_upload_service=self._file_upload_service,
            document_parser=self._document_parsers,
            document_knowledge=await self.get_document_knowledge_service(),
        )

    def _create_agent_execution_service(
        self,
        *,
        model_gateway: OpenAILanguageModelGateway | None,
        tool_executor: ToolExecutor | None,
    ) -> AgentExecutionService:
        graph = (
            build_agent_graph(
                model_gateway=model_gateway,
                tool_executor=tool_executor,
                max_iterations=settings.MAX_ITERATIONS,
                history_messages=settings.AGENT_HISTORY_MESSAGES,
                max_tool_calls=settings.AGENT_MAX_TOOL_CALLS,
                max_model_tokens=settings.AGENT_MAX_MODEL_TOKENS,
                max_model_cost=settings.AGENT_MAX_COST,
                checkpointer=self._checkpointer,
                approval_tool_names=(
                    frozenset({"generate_recipe"})
                    if settings.AGENT_REQUIRE_HUMAN_APPROVAL
                    else frozenset()
                ),
            )
            if model_gateway is not None and tool_executor is not None
            else None
        )
        return AgentExecutionService(
            agent_graph=graph,
            timeout_seconds=settings.AGENT_TIMEOUT,
            max_concurrency=settings.AGENT_MAX_CONCURRENCY,
            model_pricing=parse_model_pricing(settings.MODEL_PRICING_JSON),
        )

    @property
    def file_upload_service(self) -> FileUploadService:
        return self._file_upload_service

    @property
    def ingestion_queue(self) -> IngestionQueue | None:
        return self._ingestion_queue

    async def shutdown(self) -> None:
        """Release only resources that were actually initialized."""

        closers = []
        if self._document_knowledge_service is not None:
            closers.append(self._document_knowledge_service.close())
        if self._language_model_gateway is not None:
            closers.append(self._language_model_gateway.close())
        if closers:
            await asyncio.gather(*closers, return_exceptions=True)
        if self._ingestion_queue is not None:
            await self._ingestion_queue.close()

        await asyncio.to_thread(dispose_engine)
        self._resource_stack.close()
