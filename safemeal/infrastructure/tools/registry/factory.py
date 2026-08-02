"""组装本地默认工具注册表。"""

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from safemeal.application.use_cases.knowledge.service import KnowledgeService
from safemeal.application.use_cases.recipes import (
    RecipeGenerationService,
    RecipeService,
)
from safemeal.config.settings import settings
from safemeal.infrastructure.retrieval.milvus.tools import VectorSearchTool
from safemeal.infrastructure.retrieval.neo4j.tools import (
    DietarySafeRecipeQueryTool,
)
from safemeal.infrastructure.tools.registry.runtime import (
    ToolHandler,
    ToolRuntimeRegistry,
)
from safemeal.infrastructure.tools.recipes import (
    GenerateRecipeTool,
    GetRecipeTool,
    RecommendRecipesTool,
    SearchRecipesTool,
)

KnowledgeProvider = Callable[[], Awaitable[KnowledgeService]]


def create_tool_registry(
    *,
    knowledge_provider: KnowledgeProvider,
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
        "dietary_safe_recipe_query": DietarySafeRecipeQueryTool,
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
    )
