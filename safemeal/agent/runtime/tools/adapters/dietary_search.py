"""实现智能体可调用的应用层工具。"""

import asyncio


from safemeal.agent.runtime.tools.contracts.payloads import (
    DietarySafeRecipeQueryArgs,
    DietarySafeRecipeQueryResult,
)
from safemeal.agent.runtime.tools.ports.backends import DietarySearch
from safemeal.agent.runtime.tools.ports.handler import ToolHandler


# 类说明（业务或基础设施实现类）：DietarySafeRecipeQueryTool
# 作用：实现图安全食谱查询工具，封装该组件的业务处理与依赖协作。
class DietarySafeRecipeQueryTool(ToolHandler[DietarySafeRecipeQueryArgs]):
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 初始值：'dietary_safe_recipe_query'。
    name = "dietary_safe_recipe_query"
    # 字段说明：purpose
    # 作用：工具或组件的业务用途说明。
    # 初始值：'在 Neo4j 中查询菜品与食材关系，为过敏和忌口判断提供结构化证据。'。
    purpose = "在 Neo4j 中查询菜品与食材关系，为过敏和忌口判断提供结构化证据。"
    # 字段说明：use_when
    # 作用：工具适用的任务或场景说明。
    # 初始值：('问题涉及过敏、忌口、不含某食材或避开某食材', '需要判断指定菜品是否命中禁忌食材', '推荐前需要图谱侧安全候选与排除证据')。
    use_when = (
        "问题涉及过敏、忌口、不含某食材或避开某食材",
        "需要判断指定菜品是否命中禁忌食材",
        "推荐前需要图谱侧安全候选与排除证据",
    )
    # 字段说明：do_not_use_when
    # 作用：工具不适用的场景说明，供规划器避免错误选用。
    # 初始值：('用户只询问普通菜谱详情且不存在饮食安全条件', '需要读取用户记忆或修改用户画像', '图谱未返回完整证据时，不得单独据此宣称绝对安全')。
    do_not_use_when = (
        "用户只询问普通菜谱详情且不存在饮食安全条件",
        "需要读取用户记忆或修改用户画像",
        "图谱未返回完整证据时，不得单独据此宣称绝对安全",
    )
    # 字段说明：input_constraints
    # 作用：工具输入必须满足的条件说明。
    # 初始值：('excluded_ingredients 不能为空且由可信约束合并', '判断指定菜时才传 target_dish', '只能使用参数化字段，禁止传入 Cypher')。
    input_constraints = (
        "excluded_ingredients 不能为空且由可信约束合并",
        "判断指定菜时才传 target_dish",
        "只能使用参数化字段，禁止传入 Cypher",
    )
    # 字段说明：args_schema
    # 作用：工具入参的数据模型或 JSON Schema，供调用前校验参数。
    args_schema = DietarySafeRecipeQueryArgs

    # 方法说明：__init__
    # 作用：初始化图安全食谱查询工具，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   graph_search（DietarySearch）：食谱安全检索能力。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(
        self,
        graph_search: DietarySearch,
    ) -> None:
        # 实例属性说明：_graph_search
        # 作用：食谱安全检索能力。
        self._graph_search = graph_search

    # 方法说明：run
    # 作用：执行图安全食谱查询工具的业务处理流程。
    # 入参：
    #   arguments（DietarySafeRecipeQueryArgs）：按工具 Schema 校验后的调用参数。
    # 出参：DietarySafeRecipeQueryResult；图安全食谱查询工具结果。
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
