"""实现智能体可调用的应用层工具。"""

from __future__ import annotations
from safemeal.agent.runtime.tools.contracts.payloads import GetRecipeArgs

import asyncio

from safemeal.modules.recipe.contracts.catalog import (
    RecipeQuery,
    RecipeSearchResult,
)
from safemeal.modules.recipe.contracts.generation import RecipeGenerationRequest
from safemeal.modules.recipe.application import (
    RecipeService,
)
from safemeal.agent.runtime.tools.ports.handler import ToolHandler
from safemeal.modules.recipe.contracts.generated import GeneratedRecipe
from safemeal.modules.recipe.contracts.models import Recipe


# 类说明（业务或基础设施实现类）：SearchRecipesTool
# 作用：实现已有食谱检索工具，封装该组件的业务处理与依赖协作。
class SearchRecipesTool(ToolHandler[RecipeQuery]):
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 初始值：'search_recipes'。
    name = "search_recipes"
    # 字段说明：purpose
    # 作用：工具或组件的业务用途说明。
    # 初始值：'按名称或结构化条件查找已经存在的菜谱及完整食材证据。'。
    purpose = "按名称或结构化条件查找已经存在的菜谱及完整食材证据。"
    # 字段说明：use_when
    # 作用：工具适用的任务或场景说明。
    use_when = (
        "用户询问某道具体菜的材料或做法",
        "需要按食材、菜系、时间或营养条件筛选已有菜谱",
        "复杂菜单规划需要按分类批量召回轻量候选",
        "需要为后续饮食安全复核提供结构化食材证据",
    )
    # 字段说明：do_not_use_when
    # 作用：工具不适用的场景说明，供规划器避免错误选用。
    do_not_use_when = (
        "用户要求创作数据库中不存在的新菜谱，此时使用 generate_recipe",
        "用户已经提供正整数 recipe_id 并要求详情，此时使用 get_recipe",
        "用户仅询问一般烹饪知识且不需要菜谱证据",
    )
    # 字段说明：input_constraints
    # 作用：工具输入必须满足的条件说明。
    input_constraints = (
        "具体菜名查询必须设置 exact_name=true，不能用其他菜替代",
        "只使用 RecipeQuery 声明的字段，禁止传入 SQL 或租户身份",
        "过敏和禁忌排除项由可信上下文注入，模型不得删除",
        "菜单候选查询使用 category、candidate_mode 和排除已选菜参数",
    )
    # 字段说明：args_schema
    # 作用：工具入参的数据模型或 JSON Schema，供调用前校验参数。
    args_schema = RecipeQuery

    # 方法说明：__init__
    # 作用：初始化已有食谱检索工具，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   recipe_service（RecipeService）：菜谱查询推荐与生成业务服务。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, recipe_service: RecipeService) -> None:
        # 实例属性说明：_recipe_service
        # 作用：菜谱查询推荐与生成业务服务。
        self._recipe_service = recipe_service

    # 方法说明：run
    # 作用：执行已有食谱检索工具的业务处理流程。
    # 入参：
    #   arguments（RecipeQuery）：按工具 Schema 校验后的调用参数。
    # 出参：RecipeSearchResult；食谱查询与推荐结果。
    async def run(self, arguments: RecipeQuery) -> RecipeSearchResult:
        return await asyncio.to_thread(self._recipe_service.search, arguments)


# 类说明（业务或基础设施实现类）：GetRecipeTool
# 作用：实现菜谱详情读取工具，封装该组件的业务处理与依赖协作。
class GetRecipeTool(ToolHandler[GetRecipeArgs]):
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 初始值：'get_recipe'。
    name = "get_recipe"
    # 字段说明：purpose
    # 作用：工具或组件的业务用途说明。
    # 初始值：'按已知 recipe_id 读取单道菜的食材、用量、步骤和营养详情。'。
    purpose = "按已知 recipe_id 读取单道菜的食材、用量、步骤和营养详情。"
    # 字段说明：use_when
    # 作用：工具适用的任务或场景说明。
    # 初始值：('上一步工具已经返回明确的 recipe_id', '用户针对某个已知菜谱请求完整详情')。
    use_when = (
        "上一步工具已经返回明确的 recipe_id",
        "用户针对某个已知菜谱请求完整详情",
    )
    # 字段说明：do_not_use_when
    # 作用：工具不适用的场景说明，供规划器避免错误选用。
    # 初始值：('只有菜名但没有 recipe_id，此时先使用 search_recipes', '需要一次推荐多道菜，此时使用 recommend_recipes', '需要生成新菜谱')。
    do_not_use_when = (
        "只有菜名但没有 recipe_id，此时先使用 search_recipes",
        "需要一次推荐多道菜，此时使用 recommend_recipes",
        "需要生成新菜谱",
    )
    # 字段说明：input_constraints
    # 作用：工具输入必须满足的条件说明。
    # 初始值：('recipe_id 必须是参数 Schema 允许的正整数', '不得猜测或编造 recipe_id')。
    input_constraints = (
        "recipe_id 必须是参数 Schema 允许的正整数",
        "不得猜测或编造 recipe_id",
    )
    # 字段说明：args_schema
    # 作用：工具入参的数据模型或 JSON Schema，供调用前校验参数。
    args_schema = GetRecipeArgs

    # 方法说明：__init__
    # 作用：初始化菜谱详情读取工具，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   recipe_service（RecipeService）：菜谱查询推荐与生成业务服务。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, recipe_service: RecipeService) -> None:
        # 实例属性说明：_recipe_service
        # 作用：菜谱查询推荐与生成业务服务。
        self._recipe_service = recipe_service

    # 方法说明：run
    # 作用：执行菜谱详情读取工具的业务处理流程。
    # 入参：
    #   arguments（GetRecipeArgs）：按工具 Schema 校验后的调用参数。
    # 出参：Recipe；完整食谱业务模型。
    async def run(self, arguments: GetRecipeArgs) -> Recipe:
        return await asyncio.to_thread(self._recipe_service.get, arguments.recipe_id)


# 类说明（业务或基础设施实现类）：RecommendRecipesTool
# 作用：实现已有食谱安全推荐工具，封装该组件的业务处理与依赖协作。
class RecommendRecipesTool(ToolHandler[RecipeQuery]):
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 初始值：'recommend_recipes'。
    name = "recommend_recipes"
    # 字段说明：purpose
    # 作用：工具或组件的业务用途说明。
    # 初始值：'从已有结构化菜谱中推荐候选，并用确定性代码执行硬约束过滤。'。
    purpose = "从已有结构化菜谱中推荐候选，并用确定性代码执行硬约束过滤。"
    # 字段说明：use_when
    # 作用：工具适用的任务或场景说明。
    # 初始值：('用户请求一道或多道菜的推荐', '需要结合长期偏好、饮食类型、时间或食材条件排序候选')。
    use_when = (
        "用户请求一道或多道菜的推荐",
        "需要结合长期偏好、饮食类型、时间或食材条件排序候选",
    )
    # 字段说明：do_not_use_when
    # 作用：工具不适用的场景说明，供规划器避免错误选用。
    # 初始值：('用户询问某一道明确菜品的材料或详情', '用户要求创造一份全新食谱', '缺少食材证据却需要给出过敏安全结论')。
    do_not_use_when = (
        "用户询问某一道明确菜品的材料或详情",
        "用户要求创造一份全新食谱",
        "缺少食材证据却需要给出过敏安全结论",
    )
    # 字段说明：input_constraints
    # 作用：工具输入必须满足的条件说明。
    input_constraints = (
        "exclude_ingredients 和 dietary_types 是硬约束",
        "硬约束由 Tool Policy 注入，模型不得删除或弱化",
        "返回候选仍必须经过 Observer 和 Workflow 最终安全复核",
    )
    # 字段说明：args_schema
    # 作用：工具入参的数据模型或 JSON Schema，供调用前校验参数。
    args_schema = RecipeQuery

    # 方法说明：__init__
    # 作用：初始化已有食谱安全推荐工具，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   recipe_service（RecipeService）：菜谱查询推荐与生成业务服务。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, recipe_service: RecipeService) -> None:
        # 实例属性说明：_recipe_service
        # 作用：菜谱查询推荐与生成业务服务。
        self._recipe_service = recipe_service

    # 方法说明：run
    # 作用：执行已有食谱安全推荐工具的业务处理流程。
    # 入参：
    #   arguments（RecipeQuery）：按工具 Schema 校验后的调用参数。
    # 出参：RecipeSearchResult；食谱查询与推荐结果。
    async def run(self, arguments: RecipeQuery) -> RecipeSearchResult:
        return await asyncio.to_thread(self._recipe_service.recommend, arguments)


# 类说明（业务或基础设施实现类）：GenerateRecipeTool
# 作用：实现结构化菜谱生成工具，封装该组件的业务处理与依赖协作。
class GenerateRecipeTool(ToolHandler[RecipeGenerationRequest]):
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 初始值：'generate_recipe'。
    name = "generate_recipe"
    # 字段说明：purpose
    # 作用：工具或组件的业务用途说明。
    # 初始值：'生成一份新的强类型菜谱候选，并验证食材、步骤和饮食约束。'。
    purpose = "生成一份新的强类型菜谱候选，并验证食材、步骤和饮食约束。"
    # 字段说明：use_when
    # 作用：工具适用的任务或场景说明。
    # 初始值：('用户明确要求创作、定制或生成一份新食谱', '现有菜谱无法满足要求且用户接受生成候选')。
    use_when = (
        "用户明确要求创作、定制或生成一份新食谱",
        "现有菜谱无法满足要求且用户接受生成候选",
    )
    # 字段说明：do_not_use_when
    # 作用：工具不适用的场景说明，供规划器避免错误选用。
    # 初始值：('用户只是在查询已有菜谱或具体菜名', '用户只是请求推荐已有家常菜', '用户未批准当前配置要求人工确认的生成操作')。
    do_not_use_when = (
        "用户只是在查询已有菜谱或具体菜名",
        "用户只是请求推荐已有家常菜",
        "用户未批准当前配置要求人工确认的生成操作",
    )
    # 字段说明：input_constraints
    # 作用：工具输入必须满足的条件说明。
    input_constraints = (
        "必须满足 include_ingredients、exclude_ingredients 和 dietary_types",
        "食材用量、单位、步骤编号和营养字段必须通过 Pydantic 校验",
        "生成结果只是候选，不得声称已写入数据库",
    )
    # 字段说明：side_effects
    # 作用：工具可能产生的写入、外部操作等副作用说明。
    # 初始值：('调用外部大模型并产生 Token 成本',)。
    side_effects = ("调用外部大模型并产生 Token 成本",)
    # 字段说明：requires_approval
    # 作用：执行该工具或动作前是否需要人工确认。
    # 初始值：True。
    requires_approval = True
    # 字段说明：idempotent
    # 作用：相同调用重复执行是否不会产生额外业务副作用。
    # 初始值：False。
    idempotent = False
    # 字段说明：args_schema
    # 作用：工具入参的数据模型或 JSON Schema，供调用前校验参数。
    args_schema = RecipeGenerationRequest

    # 方法说明：__init__
    # 作用：初始化结构化菜谱生成工具，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   recipe_service（RecipeService）：菜谱查询推荐与生成业务服务。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, recipe_service: RecipeService) -> None:
        # 实例属性说明：_recipe_service
        # 作用：菜谱查询推荐与生成业务服务。
        self._recipe_service = recipe_service

    # 方法说明：run
    # 作用：执行结构化菜谱生成工具的业务处理流程。
    # 入参：
    #   arguments（RecipeGenerationRequest）：按工具 Schema 校验后的调用参数。
    # 出参：GeneratedRecipe；模型生成菜谱。
    async def run(self, arguments: RecipeGenerationRequest) -> GeneratedRecipe:
        return await self._recipe_service.generate(arguments)


__all__ = [
    "GetRecipeArgs",
    "GetRecipeTool",
    "GenerateRecipeTool",
    "RecommendRecipesTool",
    "SearchRecipesTool",
]
