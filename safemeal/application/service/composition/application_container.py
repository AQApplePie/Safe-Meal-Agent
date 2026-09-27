"""Central ownership of application services and external resources."""

from __future__ import annotations

import asyncio
import json
from contextlib import ExitStack
from threading import RLock
from typing import Optional

from safemeal.application.service.composition.model_factory import (
    create_language_model_gateway,
)
from safemeal.application.agent.graph import build_agent_graph
from safemeal.application.workflow.graph import (
    build_chat_workflow,
    build_resume_workflow,
)
from safemeal.application.workflow.runner import ChatWorkflow
from safemeal.application.service.composition.dietary_search_factory import (
    create_dietary_search,
)
from safemeal.infrastructure.operations.telemetry import export_agent_trace
from safemeal.application.workflow.context.builder import (
    AgentContextBuilder,
    create_default_agent_context_providers,
)
from safemeal.application.workflow.context.conversation_context import (
    ConversationContextWindow,
)
from safemeal.application.observability.cost import parse_model_pricing
from safemeal.application.ports.tools.tool_executor import ToolExecutor
from safemeal.application.ports.ingestion.ingestion_queue import IngestionQueue
from safemeal.application.exceptions import FeatureUnavailableError
from safemeal.application.agent.execution_service import (
    AgentExecutionService,
)
from safemeal.application.service.chat.chat_turn_service import ChatTurnService
from safemeal.application.service.chat.chat_session_service import ChatSessionService
from safemeal.application.service.chat.turn_persistence import ChatTurnPersistence
from safemeal.application.service.knowledge.document_knowledge_service import (
    DocumentKnowledgeService,
)
from safemeal.application.service.knowledge.recipe_indexing import (
    RecipeDocumentIndexer,
)
from safemeal.application.service.memory.user_memory_service import UserMemoryService
from safemeal.application.service.recipes import (
    RecipeGenerationService,
    RecipeCatalog,
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
from safemeal.infrastructure.operations.trace_store import JsonlAgentTraceStore
from safemeal.infrastructure.operations.llmops import LlmOpsExporter
from safemeal.application.agent.tool_registry import build_tool_executor
from safemeal.application.agent.tool_runtime import LocalToolExecutor
from safemeal.infrastructure.tools.mcp_client import McpClientGateway, McpServerConfig
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
from safemeal.infrastructure.persistence.chat_repository import (
    sqlalchemy_chat_unit_of_work,
)
from safemeal.infrastructure.persistence.user_memory_repository import (
    sqlalchemy_user_memory_unit_of_work,
)


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
        self._recipe_catalog: Optional[RecipeCatalog] = None
        self._language_model_gateway: Optional[OpenAILanguageModelGateway] = None
        self._document_parsers = DocumentParserRegistry()
        self._file_upload_service = FileUploadService(
            storage=LocalUploadStorage(settings.UPLOAD_DIR),
            max_size_bytes=settings.FILE_UPLOAD_MAX_MB * 1024 * 1024,
        )
        self._trace_store = JsonlAgentTraceStore(settings.AGENT_TRACE_PATH)
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
        raw_mcp_servers = json.loads(settings.MCP_EXTERNAL_SERVERS_JSON)
        self._mcp_client_gateway = (
            McpClientGateway(
                [
                    McpServerConfig(
                        name=str(item["name"]),
                        url=str(item["url"]),
                        headers={
                            str(k): str(v) for k, v in item.get("headers", {}).items()
                        },
                    )
                    for item in raw_mcp_servers
                ]
            )
            if raw_mcp_servers
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

    def get_recipe_catalog(self) -> RecipeCatalog:
        """Return the process-scoped structured recipe application service."""

        if self._recipe_catalog is None:
            with self._singleton_lock:
                if self._recipe_catalog is None:
                    self._recipe_catalog = RecipeCatalog(SqlAlchemyRecipeRepository())
        return self._recipe_catalog

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
                    if self._mcp_client_gateway is not None:
                        enabled_tools.add("external_mcp_call")
                    self._tool_executor = build_tool_executor(
                        document_knowledge_provider=self.get_document_knowledge_service,
                        recipe_catalog=self.get_recipe_catalog(),
                        recipe_generation_service=RecipeGenerationService(
                            self.get_language_model_gateway()
                        ),
                        enabled_tools=enabled_tools,
                        timeout_seconds=settings.AGENT_TOOL_TIMEOUT,
                        mcp_client_gateway=self._mcp_client_gateway,
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
            history_messages=settings.AGENT_HISTORY_SCAN_MESSAGES,
        )

    def get_chat_session_service(self) -> ChatSessionService:
        """Build session use cases with the production SQLAlchemy UoW."""

        return ChatSessionService(uow_factory=sqlalchemy_chat_unit_of_work)

    def get_user_memory_service(self) -> UserMemoryService:
        """Build user-memory use cases with the production SQLAlchemy UoW."""

        return UserMemoryService(uow_factory=sqlalchemy_user_memory_unit_of_work)

    def get_agent_context_builder(self) -> AgentContextBuilder:
        """Build the production Agent context pipeline."""

        memory_service = self.get_user_memory_service()
        return AgentContextBuilder(
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
                intent_classifier=self.get_language_model_gateway()
                if settings.ENABLE_LLM
                else None,
            ),
            build_resume_workflow(agent=self.get_agent_execution_service()),
        )

    async def get_recipe_document_indexer(self) -> RecipeDocumentIndexer:
        """Build recipe indexing against the shared document-search service."""

        return RecipeDocumentIndexer(await self.get_document_knowledge_service())

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
                    frozenset({"generate_recipe", "external_mcp_call"})
                    if settings.AGENT_REQUIRE_HUMAN_APPROVAL
                    else frozenset({"external_mcp_call"})
                ),
            )
            if model_gateway is not None and tool_executor is not None
            else None
        )
        return AgentExecutionService(
            agent_graph=graph,
            timeout_seconds=settings.AGENT_TIMEOUT,
            model_name=settings.OPENAI_MODEL,
            max_concurrency=settings.AGENT_MAX_CONCURRENCY,
            trace_store=(
                self._trace_store if settings.ENABLE_AGENT_TRACE_PERSISTENCE else None
            ),
            trace_exporter=export_agent_trace,
            model_pricing=parse_model_pricing(settings.MODEL_PRICING_JSON),
            cost_currency=settings.MODEL_COST_CURRENCY,
            llmops_exporter=(
                LlmOpsExporter(settings.LLMOPS_ENDPOINT, settings.LLMOPS_API_KEY)
                if settings.LLMOPS_ENDPOINT
                else None
            ),
        )

    @property
    def file_upload_service(self) -> FileUploadService:
        return self._file_upload_service

    @property
    def trace_store(self) -> JsonlAgentTraceStore:
        return self._trace_store

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
