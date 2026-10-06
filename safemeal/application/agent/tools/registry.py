"""创建进程级工具注册表并发布工具契约。"""

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from safemeal.application.agent.tools.runtime import LocalToolExecutor
from safemeal.application.ports.tools.backends import DietarySearch
from safemeal.application.ports.tools.handler import ToolHandler
from safemeal.application.service.knowledge.document_knowledge_service import (
    DocumentKnowledgeService,
)
from safemeal.application.service.recipes import RecipeService
from safemeal.application.tool.dietary_search import DietarySafeRecipeQueryTool
from safemeal.application.tool.recipe_tools import (
    GenerateRecipeTool,
    GetRecipeTool,
    RecommendRecipesTool,
    SearchRecipesTool,
)
from safemeal.application.tool.knowledge_search import KnowledgeSearchTool
from safemeal.application.tool.constraint_verification import (
    VerifyRecipeConstraintsTool,
)

DocumentKnowledgeProvider = Callable[[], Awaitable[DocumentKnowledgeService]]


def build_tool_executor(
    *,
    document_knowledge_provider: DocumentKnowledgeProvider,
    recipe_service: RecipeService,
    enabled_tools: Iterable[str] | None = None,
    timeout_seconds: float = 60.0,
    dietary_search: DietarySearch | None = None,
) -> LocalToolExecutor:

    factories: dict[str, Callable[[], ToolHandler[Any]]] = {
        "search_recipes": lambda: SearchRecipesTool(recipe_service),
        "get_recipe": lambda: GetRecipeTool(recipe_service),
        "recommend_recipes": lambda: RecommendRecipesTool(recipe_service),
        "generate_recipe": lambda: GenerateRecipeTool(recipe_service),
        "verify_recipe_constraints": lambda: VerifyRecipeConstraintsTool(
            recipe_service
        ),
        "search_knowledge": lambda: KnowledgeSearchTool(
            document_knowledge_provider=document_knowledge_provider
        ),
    }
    if dietary_search is not None:
        factories["dietary_safe_recipe_query"] = lambda: DietarySafeRecipeQueryTool(
            dietary_search
        )
    allowed = set(factories) if enabled_tools is None else set(enabled_tools)
    unknown = allowed - factories.keys()
    if unknown:
        raise ValueError(f"启用列表包含未知 Tool：{sorted(unknown)}")
    tools = [factory() for name, factory in factories.items() if name in allowed]
    return LocalToolExecutor(tools, timeout_seconds=timeout_seconds)


__all__ = ["DocumentKnowledgeProvider", "build_tool_executor"]
