"""Central ownership of application services and external resources."""

from __future__ import annotations

import asyncio
from threading import RLock
from typing import Optional

from safemeal.application.agents.graph import build_agent_graph
from safemeal.application.agents.tool_registry import ToolRegistry
from safemeal.application.errors import FeatureUnavailableError
from safemeal.application.use_cases.agent.graph_runner_service import (
    AgentGraphRunnerService,
)
from safemeal.application.use_cases.agent.deterministic_router import (
    DeterministicFirstAgentProcessor,
)
from safemeal.application.ports import AgentProcessor
from safemeal.application.use_cases.knowledge.service import KnowledgeService
from safemeal.application.use_cases.recipes import (
    RecipeGenerationService,
    RecipeService,
)
from safemeal.application.use_cases.upload.service import UploadService
from safemeal.config.settings import settings
from safemeal.infrastructure.retrieval.milvus.factory import (
    create_knowledge_service_async,
)
from safemeal.infrastructure.llm.decision_engine import OpenAIDecisionEngine
from safemeal.infrastructure.operations.trace_store import JsonlAgentTraceStore
from safemeal.infrastructure.tools.registry.factory import create_tool_registry
from safemeal.infrastructure.tools.registry.local_registry import LocalToolRegistry
from safemeal.infrastructure.tools.registry.runtime import ToolRuntimeRegistry
from safemeal.infrastructure.ingestion.documents import DocumentParserRegistry
from safemeal.infrastructure.ingestion.storage import LocalUploadStorage
from safemeal.infrastructure.persistence.database import dispose_engine
from safemeal.infrastructure.persistence.recipe_repository import (
    SqlAlchemyRecipeRepository,
)


class AppContainer:
    """
    统一组装和释放资源
    """

    def __init__(self) -> None:
        self._knowledge: Optional[KnowledgeService] = None
        self._knowledge_lock = asyncio.Lock()
        self._singleton_lock = RLock()
        self._agent: Optional[AgentGraphRunnerService] = None
        self._agent_processor: Optional[AgentProcessor] = None
        self._tool_runtime: Optional[ToolRuntimeRegistry] = None
        self._recipe_service: Optional[RecipeService] = None
        self._decision_engine: Optional[OpenAIDecisionEngine] = None
        self._document_parsers = DocumentParserRegistry()
        self._upload = UploadService(
            storage=LocalUploadStorage(settings.UPLOAD_DIR),
            max_size_bytes=settings.FILE_UPLOAD_MAX_MB * 1024 * 1024,
        )
        self._trace_store = JsonlAgentTraceStore(settings.AGENT_TRACE_PATH)

    # 向量数据库
    async def get_knowledge_service(self) -> KnowledgeService:
        """Return the shared Milvus service, creating it off the event loop."""

        if not (settings.ENABLE_MILVUS and settings.ENABLE_EMBEDDINGS):
            raise FeatureUnavailableError("Vector knowledge search is disabled")

        if self._knowledge is None:
            async with self._knowledge_lock:
                if self._knowledge is None:
                    self._knowledge = await create_knowledge_service_async()
        return self._knowledge

    # 聊天服务
    def get_recipe_service(self) -> RecipeService:
        """Return the process-scoped structured recipe application service."""

        if self._recipe_service is None:
            with self._singleton_lock:
                if self._recipe_service is None:
                    self._recipe_service = RecipeService(SqlAlchemyRecipeRepository())
        return self._recipe_service

    def get_decision_engine(self) -> OpenAIDecisionEngine:
        """Return the single production model adapter used by Agent and generation."""

        if self._decision_engine is None:
            with self._singleton_lock:
                if self._decision_engine is None:
                    self._decision_engine = OpenAIDecisionEngine()
        return self._decision_engine

    def get_tool_runtime_registry(self) -> ToolRuntimeRegistry:
        """Return the process-scoped registry shared by the local Agent."""

        if self._tool_runtime is None:
            with self._singleton_lock:
                if self._tool_runtime is None:
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
                    self._tool_runtime = create_tool_registry(
                        knowledge_provider=self.get_knowledge_service,
                        recipe_service=self.get_recipe_service(),
                        recipe_generation_service=RecipeGenerationService(
                            self.get_decision_engine()
                        ),
                        enabled_tools=enabled_tools,
                        timeout_seconds=settings.AGENT_TOOL_TIMEOUT,
                    )
        return self._tool_runtime

    def get_agent_graph_runner_service(self) -> AgentGraphRunnerService:
        """组装本地 Agent。

        默认运行形态是模块化单体：Agent、Memory、Tool 都在主进程内本地调用，
        避免高频主链路多次 HTTP 跳转。
        """

        if not settings.ENABLE_LLM:
            raise FeatureUnavailableError("Agent LLM is disabled")
        if self._agent is None:
            with self._singleton_lock:
                if self._agent is None:
                    runtime_registry = self.get_tool_runtime_registry()
                    registry = LocalToolRegistry(runtime_registry)
                    self._agent = self._create_agent_runner(
                        engine=self.get_decision_engine(),
                        registry=registry,
                        model_name=settings.OPENAI_MODEL,
                    )
        return self._agent

    def get_agent_processor(self) -> AgentProcessor:
        """Return the deterministic-first application boundary for Agent calls."""

        if self._agent_processor is None:
            with self._singleton_lock:
                if self._agent_processor is None:
                    fallback = (
                        self.get_agent_graph_runner_service()
                        if settings.ENABLE_LLM
                        else None
                    )
                    self._agent_processor = DeterministicFirstAgentProcessor(fallback)
        return self._agent_processor

    def _create_agent_runner(
        self,
        *,
        engine: OpenAIDecisionEngine,
        registry: ToolRegistry,
        model_name: str,
    ) -> AgentGraphRunnerService:
        graph = build_agent_graph(
            engine=engine,
            registry=registry,
            max_iterations=settings.MAX_ITERATIONS,
            history_messages=settings.AGENT_HISTORY_MESSAGES,
            max_tool_calls=settings.AGENT_MAX_TOOL_CALLS,
            max_model_tokens=settings.AGENT_MAX_MODEL_TOKENS,
            max_model_cost=settings.AGENT_MAX_COST,
        )
        return AgentGraphRunnerService(
            agent_graph=graph,
            timeout_seconds=settings.AGENT_TIMEOUT,
            model_name=model_name,
            max_concurrency=settings.AGENT_MAX_CONCURRENCY,
            trace_store=(
                self._trace_store if settings.ENABLE_AGENT_TRACE_PERSISTENCE else None
            ),
        )

    @property
    def upload_service(self) -> UploadService:
        return self._upload

    @property
    def document_parsers(self) -> DocumentParserRegistry:
        return self._document_parsers

    @property
    def trace_store(self) -> JsonlAgentTraceStore:
        return self._trace_store

    async def shutdown(self) -> None:
        """Release only resources that were actually initialized."""

        closers = []
        if self._knowledge is not None:
            closers.append(self._knowledge.close())
        if self._decision_engine is not None:
            closers.append(self._decision_engine.close())
        if closers:
            await asyncio.gather(*closers, return_exceptions=True)

        await asyncio.to_thread(dispose_engine)
