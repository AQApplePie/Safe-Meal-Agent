"""组装本地默认工具注册表。"""

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from safemeal.application.use_cases.knowledge.document_knowledge_service import (
    DocumentKnowledgeService,
)
from safemeal.application.use_cases.recipes import (
    RecipeGenerationService,
    RecipeCatalog,
)
from safemeal.config.settings import settings
from safemeal.infrastructure.retrieval.milvus.vector_search_tool import VectorSearchTool
from safemeal.infrastructure.retrieval.neo4j.tools import (
    DietarySafeRecipeQueryTool,
)
from safemeal.infrastructure.tools.tool_executor import (
    LocalToolExecutor,
    ToolHandler,
)
from safemeal.infrastructure.tools.recipe_tools import (
    GenerateRecipeTool,
    GetRecipeTool,
    RecommendRecipesTool,
    SearchRecipesTool,
)

DocumentKnowledgeProvider = Callable[[], Awaitable[DocumentKnowledgeService]]


def build_tool_executor(
    *,
    document_knowledge_provider: DocumentKnowledgeProvider,
    recipe_catalog: RecipeCatalog,
    recipe_generation_service: RecipeGenerationService,
    enabled_tools: Iterable[str] | None = None,
    timeout_seconds: float | None = None,
) -> LocalToolExecutor:
    """创建具体工具并暴露给本地 Tool runtime。"""

    factories: dict[str, Callable[[], ToolHandler[Any]]] = {
        "search_recipes": lambda: SearchRecipesTool(recipe_catalog),
        "get_recipe": lambda: GetRecipeTool(recipe_catalog),
        "recommend_recipes": lambda: RecommendRecipesTool(recipe_catalog),
        "generate_recipe": lambda: GenerateRecipeTool(recipe_generation_service),
        "dietary_safe_recipe_query": DietarySafeRecipeQueryTool,
        "milvus_vector_search": lambda: VectorSearchTool(
            document_knowledge_provider=document_knowledge_provider
        ),
    }
    allowed = set(factories) if enabled_tools is None else set(enabled_tools)
    unknown = allowed - factories.keys()
    if unknown:
        raise ValueError(f"启用列表包含未知 Tool：{sorted(unknown)}")
    tools = [factory() for name, factory in factories.items() if name in allowed]

    return LocalToolExecutor(
        tools,
        timeout_seconds=timeout_seconds or settings.AGENT_TOOL_TIMEOUT,
    )
