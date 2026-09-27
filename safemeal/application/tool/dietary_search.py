"""Neo4j dietary safety Agent tools."""

import asyncio


from safemeal.application.contracts.tools.payloads import (
    DietarySafeRecipeQueryArgs,
    DietarySafeRecipeQueryResult,
)
from safemeal.application.ports.tools.backends import DietarySearch
from safemeal.application.ports.tools.handler import ToolHandler


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
        graph_search: DietarySearch,
    ) -> None:
        self._graph_search = graph_search

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
