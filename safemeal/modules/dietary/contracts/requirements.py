"""定义跨层传递的稳定数据契约。"""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .constraints import DietaryConstraint, RecipeSafetyRecord
from .control_plane import ResolvedConstraints


# 类说明（数据契约类）：DietaryPreference
# 作用：描述饮食软偏好的结构、类型及可校验字段。
class DietaryPreference(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")
    # 字段说明：kind
    # 作用：当前业务记录或操作的类型。
    # 类型：Literal['taste', 'avoid_ingredient', 'include_ingredient', 'max_minutes', 'dietary_type', 'equipment', 'other']。
    # 取值说明：
    #   taste：口味偏好。
    #   avoid_ingredient：要求避开的具体食材。
    #   include_ingredient：要求包含的具体食材。
    #   max_minutes：可接受的制作时长上限，单位为分钟。
    #   dietary_type：饮食类型要求。
    #   equipment：厨具要求。
    #   other：其他未单独列出的类别。
    kind: Literal[
        "taste",
        "avoid_ingredient",
        "include_ingredient",
        "max_minutes",
        "dietary_type",
        "equipment",
        "other",
    ]
    # 字段说明：value
    # 作用：偏好的具体内容；max_minutes 为分钟数字字符串，dietary_type 为饮食类型，其余为对应偏好文本。
    # 类型：str。
    # 配置：最小长度=1；最大长度=200。
    value: str = Field(min_length=1, max_length=200)
    # 字段说明：required
    # 作用：当前约束必须满足的数量或条件。
    # 类型：bool。
    # 初始值：False。
    required: bool = False
    # 字段说明：source
    # 作用：数据来源标识或提供该数据的对象。
    # 类型：Literal['input', 'history', 'memory', 'provided']。
    # 取值说明：
    #   input：由当前输入提供。
    #   history：由历史数据提供。
    #   memory：更新用户长期记忆。
    #   provided：由调用方显式提供。
    source: Literal["input", "history", "memory", "provided"]

    # 方法说明：validate_value
    # 作用：校验饮食偏好的类型与取值组合，拒绝无效时间上限或饮食类型。
    # 入参：
    #   无显式入参。
    # 出参：当前模型实例；业务偏好校验通过后返回自身。
    @model_validator(mode="after")
    def validate_value(self):
        if self.kind == "max_minutes" and (
            not self.value.isdigit() or not 1 <= int(self.value) <= 10080
        ):
            raise ValueError("max_minutes must be between 1 and 10080")
        if self.kind == "dietary_type" and self.value not in {
            "vegetarian",
            "vegan",
            "pescatarian",
        }:
            raise ValueError("unsupported dietary type")
        return self


# 类说明（数据契约类）：DietaryRequirements
# 作用：描述本轮冻结的饮食执行要求的结构、类型及可校验字段。
class DietaryRequirements(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(extra="forbid")
    # 字段说明：allergies
    # 作用：用户过敏项，作为食材安全审查的硬性排除条件。
    # 类型：DietaryConstraint。
    # 配置：默认值工厂（每次创建独立对象）=lambda: DietaryConstraint(active=False)。
    allergies: DietaryConstraint = Field(
        default_factory=lambda: DietaryConstraint(active=False)
    )
    # 字段说明：restrictions
    # 作用：用户饮食限制，作为菜谱过滤的硬性要求。
    # 类型：DietaryConstraint。
    # 配置：默认值工厂（每次创建独立对象）=lambda: DietaryConstraint(active=False)。
    restrictions: DietaryConstraint = Field(
        default_factory=lambda: DietaryConstraint(active=False)
    )
    # 字段说明：preferences
    # 作用：饮食偏好集合；turn_preferences 仅对本轮生效。
    # 类型：list[DietaryPreference]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    preferences: list[DietaryPreference] = Field(default_factory=list)
    # 字段说明：resolved
    # 作用：经过冲突处理后的有效约束或解析结果。
    # 类型：ResolvedConstraints。
    # 配置：默认值工厂（每次创建独立对象）=ResolvedConstraints。
    resolved: ResolvedConstraints = Field(default_factory=ResolvedConstraints)


# 类说明（数据契约类）：PreferenceAssessment
# 作用：描述菜谱软偏好评分结果的结构、类型及可校验字段。
class PreferenceAssessment(BaseModel):
    # 字段说明：preference
    # 作用：用户的单条软偏好。
    # 类型：DietaryPreference。
    preference: DietaryPreference
    # 字段说明：status
    # 作用：HTTP 状态码或业务状态。
    # 类型：Literal['satisfied', 'not_satisfied', 'unknown']。
    # 取值说明：
    #   satisfied：条件已满足。
    #   not_satisfied：条件未满足。
    #   unknown：证据不足，无法作出确定结论。
    status: Literal["satisfied", "not_satisfied", "unknown"]
    # 字段说明：reason
    # 作用：规划或审核给出的理由说明。
    # 类型：str。
    reason: str


# 类说明（数据契约类）：RecipeReview
# 作用：描述单道食谱安全审核结果的结构、类型及可校验字段。
class RecipeReview(BaseModel):
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 类型：str。
    name: str
    # 字段说明：decision
    # 作用：规划、约束或审批形成的决策。
    # 类型：Literal['passed', 'excluded', 'unknown']。
    # 取值说明：
    #   passed：审核通过。
    #   excluded：因条件不满足而排除。
    #   unknown：证据不足，无法作出确定结论。
    decision: Literal["passed", "excluded", "unknown"]
    # 字段说明：allergy_status
    # 作用：菜谱针对用户过敏约束的审核结论。
    # 类型：Literal['safe', 'excluded', 'unknown']。
    # 取值说明：
    #   safe：安全审核通过。
    #   excluded：因条件不满足而排除。
    #   unknown：证据不足，无法作出确定结论。
    allergy_status: Literal["safe", "excluded", "unknown"]
    # 字段说明：preference_status
    # 作用：菜谱满足用户偏好的程度。
    # 类型：Literal['satisfied', 'partial', 'not_satisfied', 'unknown', 'not_applicable']。
    # 取值说明：
    #   satisfied：条件已满足。
    #   partial：仅部分条件或目标满足。
    #   not_satisfied：条件未满足。
    #   unknown：证据不足，无法作出确定结论。
    #   not_applicable：该项条件不适用。
    preference_status: Literal[
        "satisfied", "partial", "not_satisfied", "unknown", "not_applicable"
    ]
    # 字段说明：preferences
    # 作用：饮食偏好集合；turn_preferences 仅对本轮生效。
    # 类型：list[PreferenceAssessment]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    preferences: list[PreferenceAssessment] = Field(default_factory=list)
    # 字段说明：evidence
    # 作用：当前任务可使用的证据。
    # 类型：RecipeSafetyRecord。
    evidence: RecipeSafetyRecord


# 类说明（数据契约类）：DietaryReviewResult
# 作用：描述饮食安全复核结果的结构、类型及可校验字段。
class DietaryReviewResult(BaseModel):
    # 字段说明：recipes
    # 作用：待筛选、审核或渲染的菜谱集合。
    # 类型：list[RecipeReview]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    recipes: list[RecipeReview] = Field(default_factory=list)
    # 字段说明：missing_information
    # 作用：当前任务尚缺少的信息集合。
    # 类型：list[str]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    missing_information: list[str] = Field(default_factory=list)
