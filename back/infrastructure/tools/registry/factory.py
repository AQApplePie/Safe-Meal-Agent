"""组装本地默认工具注册表。"""

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from SafeMealAgent.back.application.use_cases.knowledge.service import KnowledgeService
from SafeMealAgent.back.application.use_cases.recipes import RecipeGenerationService, RecipeService
from SafeMealAgent.back.config.settings import settings
from SafeMealAgent.back.infrastructure.operations.rate_limit import RedisTokenBucket
from SafeMealAgent.back.infrastructure.retrieval.lightrag.service import LightRAGService
from SafeMealAgent.back.infrastructure.retrieval.lightrag.tools import LightRAGSearchTool
from SafeMealAgent.back.infrastructure.retrieval.milvus.tools import VectorSearchTool
from SafeMealAgent.back.infrastructure.retrieval.neo4j.tools import (
    DietarySafeRecipeQueryTool,
    Neo4jReadonlyTool,
    Neo4jSchemaTool,
)
from SafeMealAgent.back.infrastructure.tools.registry.runtime import ToolHandler, ToolRuntimeRegistry
from SafeMealAgent.back.infrastructure.tools.recipes import (
    GenerateRecipeTool,
    GetRecipeTool,
    RecommendRecipesTool,
    SearchRecipesTool,
)

KnowledgeProvider = Callable[[], Awaitable[KnowledgeService]]
LightRAGProvider = Callable[[], LightRAGService]


def create_tool_registry(
    *,
    knowledge_provider: KnowledgeProvider,
    lightrag_provider: LightRAGProvider,
    recipe_service: RecipeService,
    recipe_generation_service: RecipeGenerationService,
    enabled_tools: Iterable[str] | None = None,
    timeout_seconds: float | None = None,
) -> ToolRuntimeRegistry:
    """创建具体工具并暴露给本地 Tool runtime。"""

    factories: dict[str, Callable[[], ToolHandler[Any]]] = {
        "search_recipes": lambda: SearchRecipesTool(recipe_service),
        "get_recipe": lambda: GetRecipeTool(recipe_service),
        "recommend_recipes": lambda: RecommendRecipesTool(recipe_service),
        "generate_recipe": lambda: GenerateRecipeTool(recipe_generation_service),
        "neo4j_schema": Neo4jSchemaTool,
        "neo4j_readonly_query": Neo4jReadonlyTool,
        "dietary_safe_recipe_query": DietarySafeRecipeQueryTool,
        "lightrag_search": lambda: LightRAGSearchTool(
            service_provider=lightrag_provider
        ),
        "milvus_vector_search": lambda: VectorSearchTool(
            service_provider=knowledge_provider
        ),
    }
    allowed = set(factories) if enabled_tools is None else set(enabled_tools)
    unknown = allowed - factories.keys()
    if unknown:
        raise ValueError(f"启用列表包含未知 Tool：{sorted(unknown)}")
    tools = [factory() for name, factory in factories.items() if name in allowed]

    return ToolRuntimeRegistry(
        tools,
        timeout_seconds=timeout_seconds or settings.AGENT_TOOL_TIMEOUT,
        distributed_limiter=(
            RedisTokenBucket(settings.REDIS_RATE_LIMIT_URL, prefix="safemeal:tool")
            if settings.REDIS_RATE_LIMIT_URL
            else None
        ),
        rate_limit_per_minute=settings.TOOL_RATE_LIMIT_PER_MINUTE,
    )
