"""定义跨层传递的稳定数据契约。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ConstraintSource = Literal[
    "current_input",
    "explicit_carryover",
    "persistent_memory",
    "history_context",
]
ConstraintScope = Literal["current_turn", "current_meal", "conversation", "persistent"]
ConstraintStrength = Literal[
    "hard_safety", "strong_requirement", "soft_preference", "menu_goal"
]
ContextRelation = Literal["new_task", "continuation", "reference", "modification"]


# 类说明（数据契约类）：ConstraintStatement
# 作用：描述请求中的约束语句的结构、类型及可校验字段。
class ConstraintStatement(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：是否禁止构造后修改字段=True；额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(frozen=True, extra="forbid")
    # 字段说明：type
    # 作用：该记录或约束的业务类别，具体成员含义见下方取值说明。
    # 类型：Literal['allergy', 'restriction', 'avoid', 'include', 'food_category', 'avoid_food_category', 'max_minutes', 'dietary_type', 'equipment', 'taste']。
    # 取值说明：
    #   allergy：过敏约束。
    #   restriction：饮食限制。
    #   avoid：要求避开的食物或属性。
    #   include：要求包含的食物或属性。
    #   food_category：要求包含的食材分类。
    #   avoid_food_category：要求排除的食材分类。
    #   max_minutes：可接受的制作时长上限，单位为分钟。
    #   dietary_type：饮食类型要求。
    #   equipment：厨具要求。
    #   taste：口味偏好。
    type: Literal[
        "allergy",
        "restriction",
        "avoid",
        "include",
        "food_category",
        "avoid_food_category",
        "max_minutes",
        "dietary_type",
        "equipment",
        "taste",
    ]
    # 字段说明：value
    # 作用：当前约束的具体内容，结合 type 解释为食材、口味、饮食类型、时间或厨具等。
    # 类型：str。
    # 配置：最小长度=1；最大长度=200。
    value: str = Field(min_length=1, max_length=200)
    # 字段说明：owner
    # 作用：约束所属的用餐参与者，self 表示当前用户自身。
    # 类型：str。
    # 配置：默认值='self'；最小长度=1；最大长度=80。
    owner: str = Field(default="self", min_length=1, max_length=80)
    # 字段说明：strength
    # 作用：约束的优先级强度，决定冲突处理和是否强制过滤。
    # 类型：ConstraintStrength。
    # 取值说明：
    #   hard_safety：不可弱化的安全硬约束。
    #   strong_requirement：用户明确要求必须满足的条件。
    #   soft_preference：尽量满足的软性偏好。
    #   menu_goal：菜单分类、数量等规划目标。
    strength: ConstraintStrength
    # 字段说明：source
    # 作用：数据来源标识或提供该数据的对象。
    # 类型：ConstraintSource。
    # 初始值：'current_input'。
    # 取值说明：
    #   current_input：来源于当前用户输入。
    #   explicit_carryover：用户明确要求沿用的历史条件。
    #   persistent_memory：来源于用户长期记忆。
    #   history_context：来源于历史对话上下文。
    source: ConstraintSource = "current_input"
    # 字段说明：scope
    # 作用：当前请求或查询的可信范围。
    # 类型：ConstraintScope。
    # 初始值：'current_turn'。
    # 取值说明：
    #   current_turn：仅当前轮生效。
    #   current_meal：本次用餐任务内生效。
    #   conversation：当前会话内生效。
    #   persistent：跨会话持久生效。
    scope: ConstraintScope = "current_turn"
