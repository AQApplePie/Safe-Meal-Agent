"""Typed Agent tools adapters for structured recipe use cases."""

from __future__ import annotations
from safemeal.application.contracts.tools.payloads import GetRecipeArgs

import asyncio

from safemeal.application.contracts.recipes.catalog import (
    RecipeQuery,
    RecipeSearchResult,
)
from safemeal.application.contracts.recipes.generation import RecipeGenerationRequest
from safemeal.application.service.recipes import (
    RecipeService,
)
from safemeal.application.ports.tools.handler import ToolHandler
from safemeal.application.contracts.recipes.generated import GeneratedRecipe
from safemeal.application.contracts.recipes.models import Recipe


class SearchRecipesTool(ToolHandler[RecipeQuery]):
    """Read existing recipes by exact name or structured filters."""

    name = "search_recipes"
    purpose = "按名称或结构化条件查找已经存在的菜谱及完整食材证据。"
    use_when = (
        "用户询问某道具体菜的材料或做法",
        "需要按食材、菜系、时间或营养条件筛选已有菜谱",
        "需要为后续饮食安全复核提供结构化食材证据",
    )
    do_not_use_when = (
        "用户要求创作数据库中不存在的新菜谱，此时使用 generate_recipe",
        "用户已经提供正整数 recipe_id 并要求详情，此时使用 get_recipe",
        "用户仅询问一般烹饪知识且不需要菜谱证据",
    )
    input_constraints = (
        "具体菜名查询必须设置 exact_name=true，不能用其他菜替代",
        "只使用 RecipeQuery 声明的字段，禁止传入 SQL 或租户身份",
        "过敏和禁忌排除项由可信上下文注入，模型不得删除",
    )
    args_schema = RecipeQuery

    def __init__(self, recipe_service: RecipeService) -> None:
        self._recipe_service = recipe_service

    async def run(self, arguments: RecipeQuery) -> RecipeSearchResult:
        return await asyncio.to_thread(self._recipe_service.search, arguments)


class GetRecipeTool(ToolHandler[GetRecipeArgs]):
    """Read the canonical detail for one known recipe identifier."""

    name = "get_recipe"
    purpose = "按已知 recipe_id 读取单道菜的食材、用量、步骤和营养详情。"
    use_when = (
        "上一步工具已经返回明确的 recipe_id",
        "用户针对某个已知菜谱请求完整详情",
    )
    do_not_use_when = (
        "只有菜名但没有 recipe_id，此时先使用 search_recipes",
        "需要一次推荐多道菜，此时使用 recommend_recipes",
        "需要生成新菜谱",
    )
    input_constraints = (
        "recipe_id 必须是参数 Schema 允许的正整数",
        "不得猜测或编造 recipe_id",
    )
    args_schema = GetRecipeArgs

    def __init__(self, recipe_service: RecipeService) -> None:
        self._recipe_service = recipe_service

    async def run(self, arguments: GetRecipeArgs) -> Recipe:
        return await asyncio.to_thread(self._recipe_service.get, arguments.recipe_id)


class RecommendRecipesTool(ToolHandler[RecipeQuery]):
    """Rank existing recipes while enforcing deterministic hard filters."""

    name = "recommend_recipes"
    purpose = "从已有结构化菜谱中推荐候选，并用确定性代码执行硬约束过滤。"
    use_when = (
        "用户请求一道或多道菜的推荐",
        "需要结合长期偏好、饮食类型、时间或食材条件排序候选",
    )
    do_not_use_when = (
        "用户询问某一道明确菜品的材料或详情",
        "用户要求创造一份全新食谱",
        "缺少食材证据却需要给出过敏安全结论",
    )
    input_constraints = (
        "exclude_ingredients 和 dietary_types 是硬约束",
        "硬约束由 Tool Policy 注入，模型不得删除或弱化",
        "返回候选仍必须经过 Observer 和 Workflow 最终安全复核",
    )
    args_schema = RecipeQuery

    def __init__(self, recipe_service: RecipeService) -> None:
        self._recipe_service = recipe_service

    async def run(self, arguments: RecipeQuery) -> RecipeSearchResult:
        return await asyncio.to_thread(self._recipe_service.recommend, arguments)


class GenerateRecipeTool(ToolHandler[RecipeGenerationRequest]):
    """Create a new validated candidate recipe without persisting it."""

    name = "generate_recipe"
    purpose = "生成一份新的强类型菜谱候选，并验证食材、步骤和饮食约束。"
    use_when = (
        "用户明确要求创作、定制或生成一份新食谱",
        "现有菜谱无法满足要求且用户接受生成候选",
    )
    do_not_use_when = (
        "用户只是在查询已有菜谱或具体菜名",
        "用户只是请求推荐已有家常菜",
        "用户未批准当前配置要求人工确认的生成操作",
    )
    input_constraints = (
        "必须满足 include_ingredients、exclude_ingredients 和 dietary_types",
        "食材用量、单位、步骤编号和营养字段必须通过 Pydantic 校验",
        "生成结果只是候选，不得声称已写入数据库",
    )
    side_effects = ("调用外部大模型并产生 Token 成本",)
    requires_approval = True
    idempotent = False
    args_schema = RecipeGenerationRequest

    def __init__(self, recipe_service: RecipeService) -> None:
        self._recipe_service = recipe_service

    async def run(self, arguments: RecipeGenerationRequest) -> GeneratedRecipe:
        return await self._recipe_service.generate(arguments)


__all__ = [
    "GetRecipeArgs",
    "GetRecipeTool",
    "GenerateRecipeTool",
    "RecommendRecipesTool",
    "SearchRecipesTool",
]
