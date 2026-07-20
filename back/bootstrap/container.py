"""Central ownership of application services and external resources."""

from __future__ import annotations

import asyncio
import json
from threading import RLock
from typing import Optional, cast

from SafeMealAgent.back.application.agents.graph import build_agent_graph
from SafeMealAgent.back.application.agents.tool_registry import ToolRegistry
from SafeMealAgent.back.application.errors import FeatureUnavailableError
from SafeMealAgent.back.application.contracts.lightrag import SearchMode
from SafeMealAgent.back.application.use_cases.agent.graph_runner_service import (
    AgentGraphRunnerService,
)
from SafeMealAgent.back.application.use_cases.knowledge.service import KnowledgeService
from SafeMealAgent.back.application.use_cases.recipes import RecipeGenerationService, RecipeService
from SafeMealAgent.back.application.use_cases.upload.service import UploadService
from SafeMealAgent.back.config.settings import settings
from SafeMealAgent.back.infrastructure.retrieval.milvus.factory import create_knowledge_service_async
from SafeMealAgent.back.infrastructure.retrieval.lightrag.service import LightRAGService
from SafeMealAgent.back.infrastructure.retrieval.neo4j.service import Neo4jGraphService
from SafeMealAgent.back.infrastructure.llm.decision_engine import OpenAIDecisionEngine
from SafeMealAgent.back.infrastructure.operations.failure_queue import JsonlFailureCollector
from SafeMealAgent.back.infrastructure.operations.rate_limit import RedisFairQueueLimiter
from SafeMealAgent.back.infrastructure.operations.trace_store import JsonlAgentTraceStore
from SafeMealAgent.back.infrastructure.tools.registry.factory import create_tool_registry
from SafeMealAgent.back.infrastructure.tools.registry.local_registry import LocalToolRegistry
from SafeMealAgent.back.infrastructure.tools.registry.runtime import ToolRuntimeRegistry
from SafeMealAgent.back.infrastructure.ingestion.connectors import (
    FeishuDocumentConnector,
    HTTPSourceConnector,
    LocalFileConnector,
    S3SourceConnector,
    SourceConnectorRegistry,
)
from SafeMealAgent.back.infrastructure.ingestion.documents import (
    ApacheTikaParser,
    DocumentParserRegistry,
)
from SafeMealAgent.back.infrastructure.ingestion.storage import LocalUploadStorage
from SafeMealAgent.back.infrastructure.ingestion.sync import (
    JsonSyncStateStore,
    SourceSyncService,
    SyncJob,
    SyncScheduler,
)
from SafeMealAgent.back.infrastructure.persistence.database import dispose_engine
from SafeMealAgent.back.infrastructure.persistence.recipe_repository import SqlAlchemyRecipeRepository
from SafeMealAgent.back.shared.contracts.feedback import FailureCollector


class AppContainer:
    """
    统一组装和释放资源
    """

    def __init__(self) -> None:
        self._knowledge: Optional[KnowledgeService] = None
        self._knowledge_lock = asyncio.Lock()
        self._singleton_lock = RLock()
        self._neo4j: Optional[Neo4jGraphService] = None
        self._lightrag: Optional[LightRAGService] = None
        self._agent: Optional[AgentGraphRunnerService] = None
        self._tool_runtime: Optional[ToolRuntimeRegistry] = None
        self._recipe_service: Optional[RecipeService] = None
        self._decision_engine: Optional[OpenAIDecisionEngine] = None
        self._source_sync: Optional[SourceSyncService] = None
        self._sync_scheduler: Optional[SyncScheduler] = None
        self._distributed_queue = (
            RedisFairQueueLimiter(settings.REDIS_RATE_LIMIT_URL)
            if settings.REDIS_RATE_LIMIT_URL
            else None
        )
        tika = (
            ApacheTikaParser(
                settings.TIKA_URL,
                timeout=settings.TIKA_TIMEOUT,
                max_extracted_chars=settings.TIKA_MAX_EXTRACTED_CHARS,
            )
            if settings.TIKA_ENABLED
            else None
        )
        self._document_parsers = DocumentParserRegistry(tika=tika)
        self._upload = UploadService(
            storage=LocalUploadStorage(settings.UPLOAD_DIR),
            max_size_bytes=settings.FILE_UPLOAD_MAX_MB * 1024 * 1024,
        )
        self._failure_collector = JsonlFailureCollector(
            settings.ONLINE_FAILURE_QUEUE_PATH
        )
        self._trace_store = JsonlAgentTraceStore(
            settings.AGENT_TRACE_PATH,
            max_bytes=settings.AGENT_TRACE_MAX_BYTES,
            backup_count=settings.AGENT_TRACE_BACKUP_COUNT,
        )

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

    def get_neo4j_graph_service(self) -> Neo4jGraphService:
        """Return the process-scoped Neo4j graph service."""

        if not settings.ENABLE_NEO4J:
            raise FeatureUnavailableError("Neo4j is disabled")
        if self._neo4j is None:
            with self._singleton_lock:
                if self._neo4j is None:
                    self._neo4j = Neo4jGraphService()
        return self._neo4j

    def get_lightrag_service(self) -> LightRAGService:
        """Return the process-scoped LightRAG graph-retrieval service."""

        if not settings.ENABLE_LIGHTRAG:
            raise FeatureUnavailableError("LightRAG is disabled")
        if self._lightrag is None:
            with self._singleton_lock:
                if self._lightrag is None:
                    self._lightrag = LightRAGService(
                        working_dir=settings.LIGHTRAG_WORKING_DIR,
                        default_mode=cast(SearchMode, settings.LIGHTRAG_RETRIEVAL_MODE),
                        default_top_k=settings.LIGHTRAG_TOP_K,
                    )
        return self._lightrag

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
                        enabled_tools.update(
                            {
                                "neo4j_schema",
                                "neo4j_readonly_query",
                                "dietary_safe_recipe_query",
                            }
                        )
                    if settings.ENABLE_LIGHTRAG:
                        enabled_tools.add("lightrag_search")
                    self._tool_runtime = create_tool_registry(
                        knowledge_provider=self.get_knowledge_service,
                        lightrag_provider=self.get_lightrag_service,
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
                    collector = (
                        self._failure_collector
                        if settings.ENABLE_ONLINE_FAILURE_CAPTURE
                        else None
                    )
                    self._agent = self._create_agent_runner(
                        engine=self.get_decision_engine(),
                        registry=registry,
                        failure_collector=collector,
                        model_name=settings.OPENAI_MODEL,
                    )
        return self._agent

    def _create_agent_runner(
        self,
        *,
        engine: OpenAIDecisionEngine,
        registry: ToolRegistry,
        model_name: str,
        failure_collector: FailureCollector | None = None,
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
            failure_collector=failure_collector,
            timeout_seconds=settings.AGENT_TIMEOUT,
            model_name=model_name,
            max_concurrency=settings.AGENT_MAX_CONCURRENCY,
            trace_store=(
                self._trace_store if settings.ENABLE_AGENT_TRACE_PERSISTENCE else None
            ),
            distributed_queue=self._distributed_queue,
            distributed_max_concurrency=settings.AGENT_DISTRIBUTED_MAX_CONCURRENCY,
            queue_wait_timeout=settings.AGENT_QUEUE_WAIT_TIMEOUT,
            queue_lease_seconds=settings.AGENT_QUEUE_LEASE_SECONDS,
        )

    @property
    def upload_service(self) -> UploadService:
        return self._upload

    @property
    def document_parsers(self) -> DocumentParserRegistry:
        return self._document_parsers

    @property
    def failure_collector(self) -> FailureCollector:
        return self._failure_collector

    @property
    def trace_store(self) -> JsonlAgentTraceStore:
        return self._trace_store

    async def get_source_sync_service(self) -> SourceSyncService:
        if self._source_sync is None:
            knowledge = await self.get_knowledge_service()
            connectors = SourceConnectorRegistry()
            connectors.register("local", LocalFileConnector(settings.SOURCE_LOCAL_ROOT))
            if settings.source_http_allowed_hosts:
                connectors.register(
                    "https", HTTPSourceConnector(settings.source_http_allowed_hosts)
                )
            if settings.SOURCE_S3_BUCKET:
                connectors.register(
                    "s3",
                    S3SourceConnector(
                        bucket=settings.SOURCE_S3_BUCKET,
                        prefix=settings.SOURCE_S3_PREFIX,
                        endpoint_url=settings.SOURCE_S3_ENDPOINT_URL,
                    ),
                )
            if settings.FEISHU_ACCESS_TOKEN:
                connectors.register(
                    "feishu", FeishuDocumentConnector(settings.FEISHU_ACCESS_TOKEN)
                )
            self._source_sync = SourceSyncService(
                connectors,
                knowledge,
                JsonSyncStateStore(settings.SOURCE_SYNC_STATE_PATH),
                parsers=self._document_parsers,
                delete_missing=settings.SOURCE_DELETE_MISSING,
            )
        return self._source_sync

    async def start_background_services(self) -> None:
        raw_jobs = json.loads(settings.SOURCE_SYNC_JOBS_JSON)
        if not raw_jobs:
            return
        jobs = [SyncJob(**item) for item in raw_jobs]
        self._sync_scheduler = SyncScheduler(await self.get_source_sync_service(), jobs)
        self._sync_scheduler.start()

    async def shutdown(self) -> None:
        """Release only resources that were actually initialized."""

        if self._sync_scheduler is not None:
            await self._sync_scheduler.stop()
        closers = []
        if self._knowledge is not None:
            closers.append(self._knowledge.close())
        if self._neo4j is not None:
            closers.append(asyncio.to_thread(self._neo4j.close))
        if self._lightrag is not None:
            closers.append(self._lightrag.cleanup())
        if self._distributed_queue is not None:
            closers.append(self._distributed_queue.close())
        if self._tool_runtime is not None:
            closers.append(self._tool_runtime.close())
        if self._decision_engine is not None:
            closers.append(self._decision_engine.close())
        if closers:
            await asyncio.gather(*closers, return_exceptions=True)

        await asyncio.to_thread(dispose_engine)
