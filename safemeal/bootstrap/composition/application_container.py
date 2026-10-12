"""集中创建并持有应用运行所需的依赖。"""

from __future__ import annotations


import asyncio
from typing import Optional

from safemeal.bootstrap.composition.model_factory import (
    create_language_model_gateway,
)
from safemeal.agent.runtime.orchestration import build_agent_graph
from safemeal.agent.workflow.graph import (
    build_chat_workflow,
    build_resume_workflow,
)
from safemeal.agent.workflow.runner import ChatWorkflow
from safemeal.bootstrap.composition.dietary_search_factory import (
    create_dietary_search,
)
from safemeal.agent.workflow.context.builder import (
    AgentContextBuilder,
    create_default_agent_context_providers,
)
from safemeal.agent.workflow.context.conversation_context import (
    ConversationContextWindow,
)
from safemeal.agent.runtime.budget import parse_model_pricing
from safemeal.agent.runtime.tools.ports.tool_executor import ToolExecutor
from safemeal.modules.knowledge.ports.ingestion.ingestion_queue import IngestionQueue
from safemeal.shared.exceptions import FeatureUnavailableError
from safemeal.agent.gateway import (
    AgentExecutionService,
)
from safemeal.agent.gateway.chat_turn_service import ChatTurnService
from safemeal.modules.conversation.application.chat_session_service import (
    ChatSessionService,
)
from safemeal.modules.conversation.application.turn_persistence import (
    ChatTurnPersistence,
)
from safemeal.agent.context.history import (
    ConversationHistoryService,
)
from safemeal.modules.knowledge.application.knowledge.document_knowledge_service import (
    DocumentKnowledgeService,
)
from safemeal.modules.conversation.application.memory.user_memory_service import (
    UserMemoryService,
)
from safemeal.modules.recipe.application import (
    RecipeService,
)
from safemeal.modules.knowledge.application.upload.file_upload_service import (
    FileUploadService,
)
from safemeal.modules.knowledge.application.upload.uploaded_document_ingestion_service import (
    UploadedDocumentIngestionService,
)
from safemeal.config.settings import settings
from safemeal.bootstrap.composition.document_knowledge_factory import (
    create_document_knowledge_service_async,
)
from safemeal.infrastructure.llm.openai_language_model_gateway import (
    OpenAILanguageModelGateway,
)
from safemeal.agent.runtime.tools import build_tool_executor, LocalToolExecutor
from safemeal.infrastructure.ingestion.document_parser import DocumentParserRegistry
from safemeal.infrastructure.ingestion.local_upload_storage import LocalUploadStorage
from safemeal.infrastructure.ingestion.redis_queue import RedisIngestionQueue
from safemeal.infrastructure.persistence.threaded_checkpoint import (
    ThreadedCheckpointSaver,
)
from safemeal.infrastructure.persistence.checkpoint_serializer import (
    ContractCheckpointSerializer,
)
from safemeal.infrastructure.persistence.langgraph_checkpoint import (
    SqliteCheckpointSaver,
)
from safemeal.modules.recipe.ports.recipe_provider import RecipeProvider
from safemeal.infrastructure.retrieval.local_recipe_catalog import (
    LocalRecipeDocumentCatalog,
)
from safemeal.infrastructure.retrieval.wikibooks_recipe_provider import (
    WikibooksRecipeProvider,
)
from safemeal.infrastructure.nlu.local_request_understanding import (
    LocalModelRequestUnderstandingGateway,
)
from safemeal.agent.understanding.request_understanding import (
    RuleBasedRequestUnderstandingGateway,
)
from safemeal.infrastructure.persistence.chat_repository import (
    sqlalchemy_chat_unit_of_work,
)
from safemeal.infrastructure.persistence.user_memory_repository import (
    sqlalchemy_user_memory_unit_of_work,
)


from safemeal.bootstrap.composition.platform_container import PlatformContainer


# 类说明（依赖装配类）：ApplicationContainer
# 作用：集中构建与管理完整 Agent 应用依赖容器中的业务服务和基础设施资源。
class ApplicationContainer(PlatformContainer):
    # 方法说明：__init__
    # 作用：初始化完整 Agent 应用依赖容器，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self) -> None:
        super().__init__(settings)
        # 实例属性说明：_document_knowledge_service
        # 作用：延迟创建并复用的文档入库与检索服务。
        # 类型：Optional[DocumentKnowledgeService]。
        # 初始值：None。
        self._document_knowledge_service: Optional[DocumentKnowledgeService] = None
        # 实例属性说明：_document_knowledge_lock
        # 作用：保护文档知识服务首次创建的异步互斥锁。
        self._document_knowledge_lock = asyncio.Lock()
        # 实例属性说明：_agent_execution_service
        # 作用：延迟创建并复用的 Agent 图执行服务。
        # 类型：Optional[AgentExecutionService]。
        # 初始值：None。
        self._agent_execution_service: Optional[AgentExecutionService] = None
        # 实例属性说明：_tool_executor
        # 作用：已装配的工具注册与执行组件。
        # 类型：Optional[LocalToolExecutor]。
        # 初始值：None。
        self._tool_executor: Optional[LocalToolExecutor] = None
        # 实例属性说明：_recipe_service
        # 作用：菜谱查询推荐与生成业务服务。
        # 类型：Optional[RecipeService]。
        # 初始值：None。
        self._recipe_service: Optional[RecipeService] = None
        # 实例属性说明：_language_model_gateway
        # 作用：延迟创建并复用的语言模型调用网关。
        # 类型：Optional[OpenAILanguageModelGateway]。
        # 初始值：None。
        self._language_model_gateway: Optional[OpenAILanguageModelGateway] = None
        # 实例属性说明：_document_parsers
        # 作用：按文件扩展名映射解析器名称与解析函数的注册表。
        self._document_parsers = DocumentParserRegistry()
        # 实例属性说明：_file_upload_service
        # 作用：文件校验与保存服务。
        self._file_upload_service = FileUploadService(
            storage=LocalUploadStorage(settings.UPLOAD_DIR),
            max_size_bytes=settings.FILE_UPLOAD_MAX_MB * 1024 * 1024,
        )
        if settings.AGENT_CHECKPOINT_DATABASE_URL:
            from langgraph.checkpoint.postgres import PostgresSaver

            # 实例属性说明：_checkpointer
            # 作用：图检查点读写适配器。
            self._checkpointer = self._resource_stack.enter_context(
                PostgresSaver.from_conn_string(settings.AGENT_CHECKPOINT_DATABASE_URL)
            )
            self._checkpointer.serde = ContractCheckpointSerializer()
            self._checkpointer.setup()
            # 实例属性说明：_checkpointer
            # 作用：图检查点读写适配器。
            self._checkpointer = ThreadedCheckpointSaver(self._checkpointer)
        else:
            # 实例属性说明：_checkpointer
            # 作用：图检查点读写适配器。
            self._checkpointer = SqliteCheckpointSaver(
                settings.AGENT_CHECKPOINT_PATH, serde=ContractCheckpointSerializer()
            )
        # 实例属性说明：_ingestion_queue
        # 作用：可选的文档入库 Redis 队列，未配置队列地址时为 None。
        self._ingestion_queue = (
            RedisIngestionQueue(
                settings.INGESTION_QUEUE_URL,
                queue_name=settings.INGESTION_QUEUE_NAME,
                ttl_seconds=settings.INGESTION_JOB_TTL_SECONDS,
            )
            if settings.INGESTION_QUEUE_URL
            else None
        )

    # 方法说明：get_document_knowledge_service
    # 作用：异步取得知识检索服务，避免阻塞事件循环。
    # 入参：
    #   无显式入参。
    # 出参：DocumentKnowledgeService；文档摄取与混合检索服务。
    async def get_document_knowledge_service(self) -> DocumentKnowledgeService:

        if not (settings.ENABLE_MILVUS and settings.ENABLE_EMBEDDINGS):
            raise FeatureUnavailableError("Vector knowledge search is disabled")

        if self._document_knowledge_service is None:
            async with self._document_knowledge_lock:
                if self._document_knowledge_service is None:
                    self._document_knowledge_service = (
                        await create_document_knowledge_service_async()
                    )
        return self._document_knowledge_service

    # 方法说明：get_recipe_service
    # 作用：提供食谱查询、详情与推荐业务服务。
    # 入参：
    #   无显式入参。
    # 出参：RecipeService；食谱查询推荐与生成业务服务。
    def get_recipe_service(self) -> RecipeService:

        if self._recipe_service is None:
            with self._singleton_lock:
                if self._recipe_service is None:
                    providers: list[RecipeProvider] = [
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
                        self._get_recipe_repository(),
                        model_gateway=self.get_language_model_gateway()
                        if settings.ENABLE_LLM
                        else None,
                        lookup_providers=tuple(providers),
                    )
        return self._recipe_service

    # 方法说明：get_language_model_gateway
    # 作用：提供语言模型调用网关。
    # 入参：
    #   无显式入参。
    # 出参：OpenAILanguageModelGateway；兼容 OpenAI 协议的语言模型调用网关。
    def get_language_model_gateway(self) -> OpenAILanguageModelGateway:

        if self._language_model_gateway is None:
            with self._singleton_lock:
                if self._language_model_gateway is None:
                    self._language_model_gateway = create_language_model_gateway()
        return self._language_model_gateway

    # 方法说明：get_tool_executor
    # 作用：提供已注册工具的执行器。
    # 入参：
    #   无显式入参。
    # 出参：LocalToolExecutor；本地工具注册与执行器。
    def get_tool_executor(self) -> LocalToolExecutor:

        if self._tool_executor is None:
            with self._singleton_lock:
                if self._tool_executor is None:
                    enabled_tools = {
                        "search_recipes",
                        "get_recipe",
                        "recommend_recipes",
                        "generate_recipe",
                        "verify_recipe_constraints",
                    }
                    if settings.ENABLE_MILVUS and settings.ENABLE_EMBEDDINGS:
                        enabled_tools.add("search_knowledge")
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

    # 方法说明：get_agent_execution_service
    # 作用：组装包含请求策略和 LangGraph 执行的本地 Agent 服务。
    # 入参：
    #   无显式入参。
    # 出参：AgentExecutionService；Agent 图执行服务。
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

    # 方法说明：get_chat_turn_persistence
    # 作用：提供聊天轮次及审批状态持久化服务。
    # 入参：
    #   无显式入参。
    # 出参：ChatTurnPersistence；聊天轮次及审批持久化服务。
    def get_chat_turn_persistence(self) -> ChatTurnPersistence:

        return ChatTurnPersistence(
            uow_factory=sqlalchemy_chat_unit_of_work,
        )

    # 方法说明：get_chat_session_service
    # 作用：提供会话及消息管理业务服务。
    # 入参：
    #   无显式入参。
    # 出参：ChatSessionService；聊天会话与历史消息管理服务。
    def get_chat_session_service(self) -> ChatSessionService:

        return ChatSessionService(uow_factory=sqlalchemy_chat_unit_of_work)

    # 方法说明：get_user_memory_service
    # 作用：提供长期记忆抽取、查询及更新服务。
    # 入参：
    #   无显式入参。
    # 出参：UserMemoryService；长期记忆管理与上下文服务。
    def get_user_memory_service(self) -> UserMemoryService:

        return UserMemoryService(uow_factory=sqlalchemy_user_memory_unit_of_work)

    # 方法说明：get_agent_context_builder
    # 作用：提供已装配的 Agent 上下文构建器。
    # 入参：
    #   无显式入参。
    # 出参：AgentContextBuilder；Agent 上下文构建器。
    def get_agent_context_builder(self) -> AgentContextBuilder:

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

    # 方法说明：get_chat_turn_service
    # 作用：提供串联持久化与 Agent Workflow 的聊天用例。
    # 入参：
    #   无显式入参。
    # 出参：ChatTurnService；单轮聊天编排服务。
    def get_chat_turn_service(self) -> ChatTurnService:

        return ChatTurnService(
            persistence=self.get_chat_turn_persistence(),
            workflow=self.get_chat_workflow(),
        )

    # 方法说明：get_chat_workflow
    # 作用：提供统一聊天 Workflow 运行入口。
    # 入参：
    #   无显式入参。
    # 出参：ChatWorkflow；聊天 Workflow 执行入口。
    def get_chat_workflow(self) -> ChatWorkflow:
        return ChatWorkflow(
            build_chat_workflow(
                agent=self.get_agent_execution_service(),
                context_builder=self.get_agent_context_builder(),
                memory_service=self.get_user_memory_service(),
                request_understanding_gateway=(
                    LocalModelRequestUnderstandingGateway(
                        settings.REQUEST_UNDERSTANDING_ENDPOINT,
                        catalog_path=settings.REQUEST_UNDERSTANDING_CATALOG_PATH,
                        timeout=settings.REQUEST_UNDERSTANDING_TIMEOUT,
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

    # 方法说明：get_uploaded_document_ingestion_service
    # 作用：提供上传文档的解析与入库服务。
    # 入参：
    #   无显式入参。
    # 出参：UploadedDocumentIngestionService；上传文档解析分块与索引服务。
    async def get_uploaded_document_ingestion_service(
        self,
    ) -> UploadedDocumentIngestionService:

        return UploadedDocumentIngestionService(
            file_upload_service=self._file_upload_service,
            document_parser=self._document_parsers,
            document_knowledge=await self.get_document_knowledge_service(),
        )

    # 方法说明：_create_agent_execution_service
    # 作用：装配 Agent 图、执行预算和上下文依赖，创建执行服务。
    # 入参：
    #   model_gateway（OpenAILanguageModelGateway | None）：语言模型调用能力。
    #   tool_executor（ToolExecutor | None）：已装配的工具注册与执行组件。
    # 出参：AgentExecutionService；Agent 图执行服务。
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

    # 方法说明：file_upload_service
    # 作用：取得容器装配的文件上传业务服务。
    # 入参：
    #   无显式入参。
    # 出参：FileUploadService；文件上传校验与保存服务。
    @property
    def file_upload_service(self) -> FileUploadService:
        return self._file_upload_service

    # 方法说明：ingestion_queue
    # 作用：取得已装配的文档摄取队列。
    # 入参：
    #   无显式入参。
    # 出参：IngestionQueue | None；文档摄取队列接口或None（未取得结果）。
    @property
    def ingestion_queue(self) -> IngestionQueue | None:
        return self._ingestion_queue

    # 方法说明：shutdown
    # 作用：关闭应用依赖与后台任务。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    async def shutdown(self) -> None:

        try:
            closers = []
            if self._document_knowledge_service is not None:
                closers.append(self._document_knowledge_service.close())
            if self._language_model_gateway is not None:
                closers.append(self._language_model_gateway.close())
            if closers:
                await asyncio.gather(*closers, return_exceptions=True)
            if self._ingestion_queue is not None:
                await self._ingestion_queue.close()

        finally:
            await super().shutdown()
