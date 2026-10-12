"""复杂菜单规划任务的可序列化执行状态。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from safemeal.shared.contracts.request_frame import (
    MenuCategory,
    MenuPlanningRequirements,
)
from safemeal.shared.types import JsonObject


# 类说明（数据契约类）：MenuExecutionPlan
# 作用：从 RequestFrame 写入 Agent 检查点的稳定目标。
class MenuExecutionPlan(BaseModel):
    """从 RequestFrame 写入 Agent 检查点的稳定目标。"""

    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")
    # 字段说明：scenario
    # 作用：当前模型调用场景。
    # 类型：str | None。
    # 初始值：None。
    scenario: str | None = None
    # 字段说明：required
    # 作用：当前约束必须满足的数量或条件。
    # 类型：dict[MenuCategory, int]。
    # 取值说明：
    #   cold_dish：凉菜分类。
    #   hot_dish：热菜分类。
    #   vegetarian：素食类型或素菜分类。
    #   meat：荤菜分类。
    #   soup：汤类分类。
    #   staple：主食分类。
    required: dict[MenuCategory, int]
    # 字段说明：distinct_recipes
    # 作用：菜单是否要求每道菜只出现一次。
    # 类型：bool。
    # 初始值：True。
    distinct_recipes: bool = True
    # 字段说明：allow_cross_category_counting
    # 作用：同一道菜能否同时计入多个分类配额，关闭时避免重复计数。
    # 类型：bool。
    # 初始值：False。
    allow_cross_category_counting: bool = False


# 类说明（数据契约类）：SelectedMenuRecipe
# 作用：已选菜品及其占用的分类配额。
class SelectedMenuRecipe(BaseModel):
    """已选菜品及其占用的分类配额。"""

    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")
    # 字段说明：recipe_id
    # 作用：目标食谱的整数标识。
    # 类型：int | None。
    # 初始值：None。
    recipe_id: int | None = None
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 类型：str。
    # 配置：最小长度=1；最大长度=255。
    name: str = Field(min_length=1, max_length=255)
    # 字段说明：assigned_category
    # 作用：当前菜品实际计入的菜单分类。
    # 类型：MenuCategory。
    # 取值说明：
    #   cold_dish：凉菜分类。
    #   hot_dish：热菜分类。
    #   vegetarian：素食类型或素菜分类。
    #   meat：荤菜分类。
    #   soup：汤类分类。
    #   staple：主食分类。
    assigned_category: MenuCategory
    # 字段说明：categories
    # 作用：当前对象所属的分类集合。
    # 类型：tuple[MenuCategory, ...]。
    # 取值说明：
    #   cold_dish：凉菜分类。
    #   hot_dish：热菜分类。
    #   vegetarian：素食类型或素菜分类。
    #   meat：荤菜分类。
    #   soup：汤类分类。
    #   staple：主食分类。
    categories: tuple[MenuCategory, ...]
    # 字段说明：credited_categories
    # 作用：当前菜品已被计入的分类集合。
    # 类型：tuple[MenuCategory, ...]。
    # 初始值：()。
    # 取值说明：
    #   cold_dish：凉菜分类。
    #   hot_dish：热菜分类。
    #   vegetarian：素食类型或素菜分类。
    #   meat：荤菜分类。
    #   soup：汤类分类。
    #   staple：主食分类。
    credited_categories: tuple[MenuCategory, ...] = ()
    # 字段说明：main_ingredients
    # 作用：菜谱主料集合。
    # 类型：tuple[str, ...]。
    # 初始值：()。
    main_ingredients: tuple[str, ...] = ()
    # 字段说明：evidence_call_id
    # 作用：提供该结论证据的工具调用标识，用于追踪证据来源。
    # 类型：str。
    evidence_call_id: str


# 类说明（数据契约类）：MenuTaskProgress
# 作用：在 Agent 多次迭代之间持续保存的确定性进度。
class MenuTaskProgress(BaseModel):
    """在 Agent 多次迭代之间持续保存的确定性进度。"""

    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(extra="forbid")
    # 字段说明：fulfilled
    # 作用：菜单目标是否已被满足。
    # 类型：dict[MenuCategory, int]。
    # 取值说明：
    #   cold_dish：凉菜分类。
    #   hot_dish：热菜分类。
    #   vegetarian：素食类型或素菜分类。
    #   meat：荤菜分类。
    #   soup：汤类分类。
    #   staple：主食分类。
    fulfilled: dict[MenuCategory, int]
    # 字段说明：remaining
    # 作用：尚未完成的配额或剩余可用预算。
    # 类型：dict[MenuCategory, int]。
    # 取值说明：
    #   cold_dish：凉菜分类。
    #   hot_dish：热菜分类。
    #   vegetarian：素食类型或素菜分类。
    #   meat：荤菜分类。
    #   soup：汤类分类。
    #   staple：主食分类。
    remaining: dict[MenuCategory, int]
    # 字段说明：selected_recipes
    # 作用：菜单中已经选定的菜品集合。
    # 类型：tuple[SelectedMenuRecipe, ...]。
    # 初始值：()。
    selected_recipes: tuple[SelectedMenuRecipe, ...] = ()
    # 字段说明：candidate_pool
    # 作用：检索后待筛选、去重和配额分配的菜品候选池。
    # 类型：tuple[JsonObject, ...]。
    # 初始值：()。
    candidate_pool: tuple[JsonObject, ...] = ()
    # 字段说明：attempted_categories
    # 作用：已经尝试检索候选的菜单分类，防止无效重复搜索。
    # 类型：dict[MenuCategory, int]。
    # 配置：默认值工厂（每次创建独立对象）=dict。
    # 取值说明：
    #   cold_dish：凉菜分类。
    #   hot_dish：热菜分类。
    #   vegetarian：素食类型或素菜分类。
    #   meat：荤菜分类。
    #   soup：汤类分类。
    #   staple：主食分类。
    attempted_categories: dict[MenuCategory, int] = Field(default_factory=dict)
    # 字段说明：exhausted_categories
    # 作用：候选已耗尽的菜单分类，供后续规划判断无法补齐的配额。
    # 类型：tuple[MenuCategory, ...]。
    # 初始值：()。
    # 取值说明：
    #   cold_dish：凉菜分类。
    #   hot_dish：热菜分类。
    #   vegetarian：素食类型或素菜分类。
    #   meat：荤菜分类。
    #   soup：汤类分类。
    #   staple：主食分类。
    exhausted_categories: tuple[MenuCategory, ...] = ()
    # 字段说明：coverage_history
    # 作用：历次候选或工具执行的覆盖记录，用于检查目标是否推进。
    # 类型：tuple[JsonObject, ...]。
    # 初始值：()。
    coverage_history: tuple[JsonObject, ...] = ()
    # 字段说明：complete
    # 作用：当前结果是否完整满足目标。
    # 类型：bool。
    # 初始值：False。
    complete: bool = False
    # 字段说明：partial_reason
    # 作用：只完成部分目标的原因。
    # 类型：str。
    # 初始值：''。
    partial_reason: str = ""
    # 字段说明：excluded_recipe_ids
    # 作用：排除的菜谱标识，避免重复推荐或返回已筛除菜品。
    # 类型：tuple[int, ...]。
    # 初始值：()。
    excluded_recipe_ids: tuple[int, ...] = ()
    # 字段说明：excluded_recipe_names
    # 作用：排除的菜名集合，在缺少标识时仍可去重。
    # 类型：tuple[str, ...]。
    # 初始值：()。
    excluded_recipe_names: tuple[str, ...] = ()

    # 方法说明：validate_non_negative_counts
    # 作用：拒绝负数菜单计数，维护配额不变量。
    # 入参：
    #   无显式入参。
    # 出参：'MenuTaskProgress'；菜单选择进度与配额缺口。
    @model_validator(mode="after")
    def validate_non_negative_counts(self) -> "MenuTaskProgress":
        counts = (*self.fulfilled.values(), *self.remaining.values())
        if any(value < 0 for value in counts):
            raise ValueError("menu progress counts cannot be negative")
        return self


# 方法说明：initialize_menu_task
# 作用：根据已确认配额创建计划和初始进度。
# 入参：
#   requirements（MenuPlanningRequirements）：本轮冻结的饮食或菜单执行要求。
#   scenario（str | None）：当前模型调用场景。
# 出参：tuple[MenuExecutionPlan, MenuTaskProgress]；菜单执行目标与分类配额、菜单选择进度与配额缺口组成的元组。
def initialize_menu_task(
    requirements: MenuPlanningRequirements,
    *,
    scenario: str | None,
) -> tuple[MenuExecutionPlan, MenuTaskProgress]:
    """根据已确认配额创建计划和初始进度。"""

    required = {item.category: item.count for item in requirements.category_quotas}
    plan = MenuExecutionPlan(
        scenario=scenario,
        required=required,
        distinct_recipes=requirements.distinct_recipes,
        allow_cross_category_counting=requirements.allow_cross_category_counting,
    )
    progress = MenuTaskProgress(
        fulfilled={category: 0 for category in required},
        remaining=dict(required),
        attempted_categories={category: 0 for category in required},
    )
    return plan, progress


__all__ = [
    "MenuExecutionPlan",
    "MenuTaskProgress",
    "SelectedMenuRecipe",
    "initialize_menu_task",
]
