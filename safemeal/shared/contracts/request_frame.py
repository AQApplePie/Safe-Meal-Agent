"""与具体模型无关的单轮请求理解契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from safemeal.modules.dietary.contracts.requirements import (
    DietaryPreference,
)
from safemeal.shared.contracts.semantic import (
    ConstraintScope as ConstraintScope,
    ConstraintSource as ConstraintSource,
    ConstraintStatement,
    ConstraintStrength as ConstraintStrength,
    ContextRelation,
)


# 类说明（数据契约类）：RequestTask
# 作用：描述用户请求任务枚举的结构、类型及可校验字段。
class RequestTask(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")
    # 字段说明：kind
    # 作用：当前业务记录或操作的类型。
    # 类型：Literal['recipe_detail', 'recipe_recommendation', 'menu_planning', 'recipe_generation', 'knowledge', 'nutrition_query', 'food_safety', 'replace', 'memory', 'clarify', 'out_of_scope']。
    # 取值说明：
    #   recipe_detail：查看指定菜谱详情。
    #   recipe_recommendation：推荐符合要求的菜谱。
    #   menu_planning：规划满足数量与分类要求的菜单。
    #   recipe_generation：生成符合要求的新菜谱。
    #   knowledge：查询饮食知识。
    #   nutrition_query：查询营养信息。
    #   food_safety：判断饮食或食材安全性。
    #   replace：替换既有菜品或任务对象。
    #   memory：更新用户长期记忆。
    #   clarify：请求用户澄清信息。
    #   out_of_scope：请求超出当前业务支持范围。
    kind: Literal[
        "recipe_detail",
        "recipe_recommendation",
        "menu_planning",
        "recipe_generation",
        "knowledge",
        "nutrition_query",
        "food_safety",
        "replace",
        "memory",
        "clarify",
        "out_of_scope",
    ]


MenuCategory = Literal[
    "cold_dish",
    "hot_dish",
    "vegetarian",
    "meat",
    "soup",
    "staple",
]


# 类说明（数据契约类）：CategoryQuota
# 作用：复杂菜单中一个可确定计数的分类配额。
class CategoryQuota(BaseModel):
    """复杂菜单中一个可确定计数的分类配额。"""

    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")
    # 字段说明：category
    # 作用：目标食材或菜品分类。
    # 类型：MenuCategory。
    # 取值说明：
    #   cold_dish：凉菜分类。
    #   hot_dish：热菜分类。
    #   vegetarian：素食类型或素菜分类。
    #   meat：荤菜分类。
    #   soup：汤类分类。
    #   staple：主食分类。
    category: MenuCategory
    # 字段说明：count
    # 作用：该菜单分类需要分配的菜品数量。
    # 类型：int。
    # 配置：最小值（含）=1；最大值（含）=20。
    count: int = Field(ge=1, le=20)


# 类说明（数据契约类）：MenuPlanningRequirements
# 作用：必须由代码验证完成度的菜单规划要求。
class MenuPlanningRequirements(BaseModel):
    """必须由代码验证完成度的菜单规划要求。"""

    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")
    # 字段说明：category_quotas
    # 作用：菜单各分类需要满足的菜品数量，内部每项由 CategoryQuota 定义。
    # 类型：tuple[CategoryQuota, ...]。
    # 配置：最小长度=1；最大长度=12。
    category_quotas: tuple[CategoryQuota, ...] = Field(min_length=1, max_length=12)
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

    # 方法说明：total_required
    # 作用：计算菜单各分类配额要求的总菜品数。
    # 入参：
    #   无显式入参。
    # 出参：int；菜单各分类配额要求的总菜品数。
    @property
    def total_required(self) -> int:
        return sum(item.count for item in self.category_quotas)


# 类说明（数据契约类）：MemoryUpdate
# 作用：描述请求理解模型的记忆更新的结构、类型及可校验字段。
class MemoryUpdate(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")
    # 字段说明：kind
    # 作用：当前业务记录或操作的类型。
    # 类型：Literal['preference', 'dislike', 'allergy', 'restriction']。
    # 取值说明：
    #   preference：喜好偏好。
    #   dislike：明确不喜欢的食物或口味。
    #   allergy：过敏约束。
    #   restriction：饮食限制。
    kind: Literal["preference", "dislike", "allergy", "restriction"]
    # 字段说明：value
    # 作用：用户明确表达的喜好、厌恶、过敏或限制内容，结合 kind 解释。
    # 类型：str。
    # 配置：最小长度=1；最大长度=100。
    value: str = Field(min_length=1, max_length=100)


# 类说明（数据契约类）：CurrentConstraint
# 作用：描述本轮已解析的当前约束的结构、类型及可校验字段。
class CurrentConstraint(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")
    # 字段说明：kind
    # 作用：当前业务记录或操作的类型。
    # 类型：Literal['allergy', 'restriction', 'food_category', 'avoid_food_category']。
    # 取值说明：
    #   allergy：过敏约束。
    #   restriction：饮食限制。
    #   food_category：要求包含的食材分类。
    #   avoid_food_category：要求排除的食材分类。
    kind: Literal["allergy", "restriction", "food_category", "avoid_food_category"]
    # 字段说明：value
    # 作用：本轮约束涉及的食材、限制内容或食物类别，结合 kind 解释。
    # 类型：str。
    # 配置：最小长度=1；最大长度=100。
    value: str = Field(min_length=1, max_length=100)


# 类说明（数据契约类）：RequestTarget
# 作用：描述用户请求目标与引用的结构、类型及可校验字段。
class RequestTarget(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")
    # 字段说明：recipe_name
    # 作用：目标菜谱名称。
    # 类型：str | None。
    # 配置：默认值=None；最大长度=255。
    recipe_name: str | None = Field(default=None, max_length=255)
    # 字段说明：ingredient
    # 作用：当前食材条目。
    # 类型：str | None。
    # 配置：默认值=None；最大长度=100。
    ingredient: str | None = Field(default=None, max_length=100)
    # 字段说明：menu_category
    # 作用：菜品在菜单配额体系中的分类。
    # 类型：MenuCategory | None。
    # 初始值：None。
    # 取值说明：
    #   cold_dish：凉菜分类。
    #   hot_dish：热菜分类。
    #   vegetarian：素食类型或素菜分类。
    #   meat：荤菜分类。
    #   soup：汤类分类。
    #   staple：主食分类。
    menu_category: MenuCategory | None = None


# 类说明（数据契约类）：RequestFrame
# 作用：当前用户输入经过归一化后形成的唯一业务语义事实。
class RequestFrame(BaseModel):
    """当前用户输入经过归一化后形成的唯一业务语义事实。"""

    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")
    # 字段说明：tasks
    # 作用：本轮请求包含的业务任务，首项作为主任务。
    # 类型：tuple[RequestTask, ...]。
    # 初始值：()。
    tasks: tuple[RequestTask, ...] = ()
    # 字段说明：memory_updates
    # 作用：本轮明确提取的记忆变更，内部由 MemoryUpdate 定义。
    # 类型：tuple[MemoryUpdate, ...]。
    # 初始值：()。
    memory_updates: tuple[MemoryUpdate, ...] = ()
    # 字段说明：current_constraints
    # 作用：仅针对当前请求生效的约束，内部由 CurrentConstraint 定义。
    # 类型：tuple[CurrentConstraint, ...]。
    # 初始值：()。
    current_constraints: tuple[CurrentConstraint, ...] = ()
    # 字段说明：turn_preferences
    # 作用：饮食偏好集合；turn_preferences 仅对本轮生效。
    # 类型：tuple[DietaryPreference, ...]。
    # 初始值：()。
    turn_preferences: tuple[DietaryPreference, ...] = ()
    # 字段说明：statements
    # 作用：完整的约束语句集合，包含值、归属、强度、来源和作用域。
    # 类型：tuple[ConstraintStatement, ...]。
    # 初始值：()。
    statements: tuple[ConstraintStatement, ...] = ()
    # 字段说明：participants
    # 作用：本轮用餐参与者标识，供约束归属和多人员场景处理。
    # 类型：tuple[str, ...]。
    # 初始值：()。
    participants: tuple[str, ...] = ()
    # 字段说明：context_relation
    # 作用：本轮输入与历史任务之间的关系，决定是否承接或修改既有任务。
    # 类型：ContextRelation。
    # 初始值：'new_task'。
    # 取值说明：
    #   new_task：开启新的独立任务。
    #   continuation：延续此前任务。
    #   reference：引用已有对象或结果。
    #   modification：修改此前任务要求。
    context_relation: ContextRelation = "new_task"
    # 字段说明：operation
    # 作用：本轮显式操作，目前仅支持 replace（替换）或 None（未指定）。
    # 类型：Literal['replace'] | None。
    # 初始值：None。
    # 取值说明：
    #   replace：替换既有菜品或任务对象。
    operation: Literal["replace"] | None = None
    # 字段说明：canonical
    # 作用：请求是否已经完成业务归一化，原始理解结果为 false。
    # 类型：bool。
    # 初始值：True。
    canonical: bool = True
    # 字段说明：target
    # 作用：本轮目标对象，由 RequestTarget 的菜名、食材和菜单分类定位。
    # 类型：RequestTarget。
    # 配置：默认值工厂（每次创建独立对象）=RequestTarget。
    target: RequestTarget = Field(default_factory=RequestTarget)
    # 字段说明：requested_fields
    # 作用：用户指定需要展示的菜谱详情字段，空集合表示没有显式点选字段。
    # 类型：tuple[Literal['ingredients', 'steps', 'time', 'nutrition'], ...]。
    # 初始值：()。
    # 取值说明：
    #   ingredients：食材清单。
    #   steps：制作步骤。
    #   time：制作时间。
    #   nutrition：营养信息。
    requested_fields: tuple[
        Literal["ingredients", "steps", "time", "nutrition"], ...
    ] = ()
    # 字段说明：exact_match_required
    # 作用：是否要求菜名精确匹配，避免以相似菜谱替代目标。
    # 类型：bool。
    # 初始值：False。
    exact_match_required: bool = False
    # 字段说明：recommendation_count
    # 作用：用户要求返回的菜谱数量。
    # 类型：int | None。
    # 配置：默认值=None；最小值（含）=1；最大值（含）=100。
    recommendation_count: int | None = Field(default=None, ge=1, le=100)
    # 字段说明：servings
    # 作用：菜谱或菜单计划的用餐人数。
    # 类型：int | None。
    # 配置：默认值=None；最小值（含）=1；最大值（含）=1000。
    servings: int | None = Field(default=None, ge=1, le=1000)
    # 即使用户没有提供分类配额，用餐时段仍用于普通配餐推荐。
    # 字段说明：meal_type
    # 作用：用餐时段，参与早餐、午餐或晚餐的推荐与菜单规划。
    # 类型：Literal['breakfast', 'lunch', 'dinner'] | None。
    # 初始值：None。
    # 取值说明：
    #   breakfast：早餐时段。
    #   lunch：午餐时段。
    #   dinner：晚餐时段。
    meal_type: Literal["breakfast", "lunch", "dinner"] | None = None
    # 字段说明：scenario
    # 作用：本轮用餐场景描述，例如聚餐等，用于推荐与菜单规划。
    # 类型：str | None。
    # 配置：默认值=None；最大长度=100。
    scenario: str | None = Field(default=None, max_length=100)
    # 字段说明：menu_planning
    # 作用：菜单规划要求，由分类配额、菜品去重和跨分类计数规则组成。
    # 类型：MenuPlanningRequirements | None。
    # 初始值：None。
    menu_planning: MenuPlanningRequirements | None = None
    # 字段说明：context_needs
    # 作用：本轮请求加载的上下文类型，可同时选择多项；安全约束仍由上下文准备流程补充。
    # 类型：tuple[Literal['recent_conversation', 'allergies', 'dietary_restrictions', 'food_preferences', 'episodic_memory', 'user_profile'], ...]。
    # 初始值：()。
    # 取值说明：
    #   recent_conversation：近期对话消息，用于承接上一轮、消解指代或修改已有任务。
    #   allergies：用户过敏记忆，用于过滤可能引发过敏的食材。
    #   dietary_restrictions：用户饮食禁忌与限制记忆，例如必须避免的食物或饮食类型。
    #   food_preferences：口味、喜好、厌恶及相关健康目标或烹饪时间记忆，用于个性化。
    #   episodic_memory：历史任务或菜单的片段记忆，用于恢复此前发生过的任务情境。
    #   user_profile：用户画像和个人事实，用于补充个性化上下文。
    context_needs: tuple[
        Literal[
            "recent_conversation",
            "allergies",
            "dietary_restrictions",
            "food_preferences",
            "episodic_memory",
            "user_profile",
        ],
        ...,
    ] = ()
    # 字段说明：confidence
    # 作用：请求理解结果的置信度，范围 0 到 1，供理解状态与澄清决策使用。
    # 类型：float。
    # 配置：默认值=1.0；最小值（含）=0；最大值（含）=1。
    confidence: float = Field(default=1.0, ge=0, le=1)
    # 字段说明：understanding_status
    # 作用：请求理解结果的可信与完整状态。
    # 类型：Literal['accepted', 'low_confidence', 'fallback', 'incomplete']。
    # 初始值：'accepted'。
    # 取值说明：
    #   accepted：理解结果通过校验，可按正常路径执行。
    #   low_confidence：理解可信度不足，可能需要澄清。
    #   fallback：使用了备用理解或执行路径。
    #   incomplete：理解或结果缺少必要信息。
    understanding_status: Literal[
        "accepted", "low_confidence", "fallback", "incomplete"
    ] = "accepted"
    # 字段说明：backend
    # 作用：产生请求理解结果的后端标识，例如 rules 或 local_model。
    # 类型：str。
    # 初始值：'rules'。
    backend: str = "rules"
    # 字段说明：fallback_used
    # 作用：是否启用了降级处理路径。
    # 类型：bool。
    # 初始值：False。
    fallback_used: bool = False
    # 字段说明：clarification_question
    # 作用：缺少关键信息或语义不确定时向用户提出的澄清问题。
    # 类型：str | None。
    # 配置：默认值=None；最大长度=300。
    clarification_question: str | None = Field(default=None, max_length=300)
    # 字段说明：validation_errors
    # 作用：理解结果的校验错误摘要，最多保留 10 条。
    # 类型：tuple[str, ...]。
    # 配置：默认值工厂（每次创建独立对象）=tuple；最大长度=10。
    validation_errors: tuple[str, ...] = Field(default_factory=tuple, max_length=10)

    # 方法说明：primary_task
    # 作用：取得请求语义框架中的主要业务任务。
    # 入参：
    #   无显式入参。
    # 出参：str；本轮请求的主任务名称。
    @property
    def primary_task(self) -> str:
        return self.tasks[0].kind if self.tasks else "out_of_scope"


# 原始契约尚未通过语义归一化，不能直接驱动 Planner。
# 类说明（业务或基础设施实现类）：RawRequestFrame
# 作用：实现模型输出的原始请求语义框架，封装该组件的业务处理与依赖协作。
class RawRequestFrame(RequestFrame):
    # 字段说明：canonical
    # 作用：请求是否已经完成业务归一化，原始理解结果为 false。
    # 类型：bool。
    # 初始值：False。
    canonical: bool = False


CanonicalRequestFrame = RequestFrame
