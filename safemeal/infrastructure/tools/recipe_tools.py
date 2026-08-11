"""Typed Agent tools adapters for structured recipe use cases."""

from __future__ import annotations

import asyncio
from pydantic import BaseModel, ConfigDict, Field

from safemeal.application.contracts.recipe_catalog import (
    RecipeQuery,
    RecipeSearchResult,
)
from safemeal.application.contracts.recipe_generation import RecipeGenerationRequest
from safemeal.application.use_cases.recipes import (
    RecipeGenerationService,
    RecipeCatalog,
)
from safemeal.infrastructure.tools.tool_executor import ToolHandler
from safemeal.modules.recipe_catalog.generated_recipe import GeneratedRecipe
from safemeal.modules.recipe_catalog.recipe_models import Recipe


class GetRecipeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: int = Field(gt=0)


class SearchRecipesTool(ToolHandler[RecipeQuery]):
    name = "search_recipes"
    description = (
        "按菜名、食材、排除食材、菜系、难度、时间和营养边界查询结构化菜谱。"
        "参数是固定字段，禁止传入SQL。"
    )
    args_schema = RecipeQuery

    def __init__(self, recipe_catalog: RecipeCatalog) -> None:
        self._recipe_catalog = recipe_catalog

    async def run(self, arguments: RecipeQuery) -> RecipeSearchResult:
        return await asyncio.to_thread(self._recipe_catalog.search, arguments)


class GetRecipeTool(ToolHandler[GetRecipeArgs]):
    name = "get_recipe"
    description = "按正整数recipe_id读取一道菜的食材、规范化用量、顺序步骤和营养信息。"
    args_schema = GetRecipeArgs

    def __init__(self, recipe_catalog: RecipeCatalog) -> None:
        self._recipe_catalog = recipe_catalog

    async def run(self, arguments: GetRecipeArgs) -> Recipe:
        return await asyncio.to_thread(self._recipe_catalog.get, arguments.recipe_id)


class RecommendRecipesTool(ToolHandler[RecipeQuery]):
    name = "recommend_recipes"
    description = (
        "在结构化菜谱上执行确定性推荐；exclude_ingredients和dietary_types是硬约束，"
        "命中候选会在普通代码中移除，不交给模型自行判断。"
    )
    args_schema = RecipeQuery

    def __init__(self, recipe_catalog: RecipeCatalog) -> None:
        self._recipe_catalog = recipe_catalog

    async def run(self, arguments: RecipeQuery) -> RecipeSearchResult:
        return await asyncio.to_thread(self._recipe_catalog.recommend, arguments)


class GenerateRecipeTool(ToolHandler[RecipeGenerationRequest]):
    name = "generate_recipe"
    description = (
        "生成一份新的强类型菜谱候选，校验食材数量/单位、连续步骤、营养边界、"
        "必选食材、过敏排除、饮食类型、份数和时间限制。不会写入数据库。"
    )
    args_schema = RecipeGenerationRequest

    def __init__(self, recipe_generation_service: RecipeGenerationService) -> None:
        self._recipe_generation_service = recipe_generation_service

    async def run(self, arguments: RecipeGenerationRequest) -> GeneratedRecipe:
        return await self._recipe_generation_service.generate_recipe(arguments)


__all__ = [
    "GetRecipeArgs",
    "GetRecipeTool",
    "GenerateRecipeTool",
    "RecommendRecipesTool",
    "SearchRecipesTool",
]
