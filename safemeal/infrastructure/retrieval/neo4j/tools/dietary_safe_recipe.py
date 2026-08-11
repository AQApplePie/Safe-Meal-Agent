"""Neo4j dietary safety Agent tools."""

import asyncio
from typing import Optional

from pydantic import BaseModel, Field

from safemeal.infrastructure.retrieval.neo4j.safe_recipe_search import (
    DietarySafeRecipeQueryResult,
    SafeRecipeGraphSearch,
)
from safemeal.infrastructure.tools.tool_executor import ToolHandler


class DietarySafeRecipeQueryArgs(BaseModel):
    """饮食忌口/过敏安全查询参数。"""

    excluded_ingredients: list[str] = Field(
        min_length=1,
        description="需要硬排除的忌口/过敏食材，例如 ['鸡蛋', '扇贝']。",
    )
    target_dish: Optional[str] = Field(
        default=None,
        description="需要判断是否适合的指定菜名；为空时返回安全推荐和排除样例。",
    )
    recommend_limit: int = Field(
        default=2,
        ge=0,
        le=10,
        description="需要返回的安全推荐数量。",
    )
    excluded_limit: int = Field(
        default=5,
        ge=0,
        le=20,
        description="需要返回的命中禁忌食材菜品数量。",
    )


class DietarySafeRecipeQueryTool(ToolHandler[DietarySafeRecipeQueryArgs]):
    name = "dietary_safe_recipe_query"
    description = (
        "针对过敏、忌口、不能吃、不含、避开等饮食安全问题，在 Neo4j 中确定性查询菜品食材。"
        "输入禁忌食材后返回 safe_recipes、excluded_recipes、unknown_recipes 和证据；"
        "判断指定菜是否适合时传 target_dish。"
    )
    args_schema = DietarySafeRecipeQueryArgs

    def __init__(
        self,
        graph_search: SafeRecipeGraphSearch | None = None,
    ) -> None:
        self._graph_search = graph_search or SafeRecipeGraphSearch()

    async def run(
        self,
        arguments: DietarySafeRecipeQueryArgs,
    ) -> DietarySafeRecipeQueryResult:
        return await asyncio.to_thread(
            self._graph_search.search,
            excluded_ingredients=arguments.excluded_ingredients,
            target_dish=arguments.target_dish,
            recommend_limit=arguments.recommend_limit,
            excluded_limit=arguments.excluded_limit,
        )
