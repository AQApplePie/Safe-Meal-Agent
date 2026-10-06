"""实现智能体可调用的应用层工具。"""

import asyncio


from safemeal.application.contracts.tools.payloads import (
    DietarySafeRecipeQueryArgs,
    DietarySafeRecipeQueryResult,
)
from safemeal.application.ports.tools.backends import DietarySearch
from safemeal.application.ports.tools.handler import ToolHandler


class DietarySafeRecipeQueryTool(ToolHandler[DietarySafeRecipeQueryArgs]):

    name = "dietary_safe_recipe_query"
    purpose = "在 Neo4j 中查询菜品与食材关系，为过敏和忌口判断提供结构化证据。"
    use_when = (
        "问题涉及过敏、忌口、不含某食材或避开某食材",
        "需要判断指定菜品是否命中禁忌食材",
        "推荐前需要图谱侧安全候选与排除证据",
    )
    do_not_use_when = (
        "用户只询问普通菜谱详情且不存在饮食安全条件",
        "需要读取用户记忆或修改用户画像",
        "图谱未返回完整证据时，不得单独据此宣称绝对安全",
    )
    input_constraints = (
        "excluded_ingredients 不能为空且由可信约束合并",
        "判断指定菜时才传 target_dish",
        "只能使用参数化字段，禁止传入 Cypher",
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
