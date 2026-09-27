"""组装本地默认工具注册表。"""

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from safemeal.application.service.knowledge.document_knowledge_service import (
    DocumentKnowledgeService,
)
from safemeal.application.service.recipes import (
    RecipeGenerationService,
    RecipeCatalog,
)
from safemeal.application.tool.vector_search import VectorSearchTool
from safemeal.application.tool.dietary_search import (
    DietarySafeRecipeQueryTool,
)
from safemeal.application.agent.tool_runtime import (
    LocalToolExecutor,
    ToolHandler,
)
from safemeal.application.tool.recipe_tools import (
    GenerateRecipeTool,
    GetRecipeTool,
    RecommendRecipesTool,
    SearchRecipesTool,
)
from safemeal.application.tool.external_mcp import ExternalMcpTool
from safemeal.application.ports.tools.backends import McpGateway, DietarySearch

DocumentKnowledgeProvider = Callable[[], Awaitable[DocumentKnowledgeService]]


def build_tool_executor(
    *,
    document_knowledge_provider: DocumentKnowledgeProvider,
    recipe_catalog: RecipeCatalog,
    recipe_generation_service: RecipeGenerationService,
    enabled_tools: Iterable[str] | None = None,
    timeout_seconds: float = 60.0,
    mcp_client_gateway: McpGateway | None = None,
    dietary_search: DietarySearch | None = None,
) -> LocalToolExecutor:
    """创建具体工具并暴露给本地 Tool runtime。"""

    factories: dict[str, Callable[[], ToolHandler[Any]]] = {
        "search_recipes": lambda: SearchRecipesTool(recipe_catalog),
        "get_recipe": lambda: GetRecipeTool(recipe_catalog),
        "recommend_recipes": lambda: RecommendRecipesTool(recipe_catalog),
        "generate_recipe": lambda: GenerateRecipeTool(recipe_generation_service),
        "milvus_vector_search": lambda: VectorSearchTool(
            document_knowledge_provider=document_knowledge_provider
        ),
    }
    if dietary_search is not None:
        factories["dietary_safe_recipe_query"] = lambda: DietarySafeRecipeQueryTool(
            dietary_search
        )
    if mcp_client_gateway is not None:
        factories["external_mcp_call"] = lambda: ExternalMcpTool(mcp_client_gateway)
    allowed = set(factories) if enabled_tools is None else set(enabled_tools)
    unknown = allowed - factories.keys()
    if unknown:
        raise ValueError(f"启用列表包含未知 Tool：{sorted(unknown)}")
    tools = [factory() for name, factory in factories.items() if name in allowed]

    return LocalToolExecutor(
        tools,
        timeout_seconds=timeout_seconds,
    )
