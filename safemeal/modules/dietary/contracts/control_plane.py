"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from safemeal.shared.contracts.semantic import ConstraintStatement
from safemeal.shared.types import JsonObject


# 类说明（数据契约类）：ResolvedConstraints
# 作用：描述合并后的饮食约束的结构、类型及可校验字段。
class ResolvedConstraints(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(extra="forbid")
    # 字段说明：hard_safety
    # 作用：必须满足的安全约束，例如过敏与饮食禁忌。
    # 类型：tuple[ConstraintStatement, ...]。
    # 初始值：()。
    hard_safety: tuple[ConstraintStatement, ...] = ()
    # 字段说明：strong_requirements
    # 作用：用户明确提出且必须满足的强要求。
    # 类型：tuple[ConstraintStatement, ...]。
    # 初始值：()。
    strong_requirements: tuple[ConstraintStatement, ...] = ()
    # 字段说明：soft_preferences
    # 作用：可参与排序但不能覆盖安全约束的软性偏好。
    # 类型：tuple[ConstraintStatement, ...]。
    # 初始值：()。
    soft_preferences: tuple[ConstraintStatement, ...] = ()
    # 字段说明：menu_goals
    # 作用：菜单数量、分类和去重等目标约束。
    # 类型：tuple[ConstraintStatement, ...]。
    # 初始值：()。
    menu_goals: tuple[ConstraintStatement, ...] = ()

    # 方法说明：active
    # 作用：合并当前各优先级约束，返回有效约束语句集合。
    # 入参：
    #   无显式入参。
    # 出参：tuple[ConstraintStatement, ...]；当前硬安全、强要求、软偏好与菜单目标组成的约束语句元组。
    @property
    def active(self) -> tuple[ConstraintStatement, ...]:
        return (
            *self.hard_safety,
            *self.strong_requirements,
            *self.soft_preferences,
            *self.menu_goals,
        )


# 类说明（数据契约类）：ToolEvidence
# 作用：描述单个工具返回的证据的结构、类型及可校验字段。
class ToolEvidence(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(extra="forbid")
    # 字段说明：recipe_name
    # 作用：目标菜谱名称。
    # 类型：str。
    # 配置：最小长度=1；最大长度=255。
    recipe_name: str = Field(min_length=1, max_length=255)
    # 字段说明：ingredients
    # 作用：菜谱使用的完整食材集合。
    # 类型：tuple[str, ...]。
    # 初始值：()。
    ingredients: tuple[str, ...] = ()
    # 字段说明：ingredients_complete
    # 作用：食材清单是否完整，缺失时不能给出确定的安全结论。
    # 类型：bool。
    # 初始值：False。
    ingredients_complete: bool = False
    # 字段说明：categories
    # 作用：当前对象所属的分类集合。
    # 类型：tuple[str, ...]。
    # 初始值：()。
    categories: tuple[str, ...] = ()
    # 字段说明：steps
    # 作用：菜谱制作步骤，按执行顺序排列。
    # 类型：tuple[str, ...]。
    # 初始值：()。
    steps: tuple[str, ...] = ()
    # 字段说明：source
    # 作用：菜谱证据的来源标识，供判断来源完整性与结果追溯。
    # 类型：str。
    # 初始值：''。
    source: str = ""
    # 字段说明：source_complete
    # 作用：来源信息是否完整，供引用与可信度检查。
    # 类型：bool。
    # 初始值：False。
    source_complete: bool = False
    # 字段说明：fields
    # 作用：待读取或校验字段集合。
    # 类型：JsonObject。
    # 配置：默认值工厂（每次创建独立对象）=dict。
    fields: JsonObject = Field(default_factory=dict)


# 类说明（数据契约类）：ConstraintDecision
# 作用：描述饮食约束执行决策的结构、类型及可校验字段。
class ConstraintDecision(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(extra="forbid")
    # 字段说明：status
    # 作用：HTTP 状态码或业务状态。
    # 类型：Literal['satisfied', 'violated', 'unknown']。
    # 取值说明：
    #   satisfied：条件已满足。
    #   violated：条件被违反。
    #   unknown：证据不足，无法作出确定结论。
    status: Literal["satisfied", "violated", "unknown"]
    # 字段说明：constraint
    # 作用：当前饮食硬约束。
    # 类型：ConstraintStatement。
    constraint: ConstraintStatement
    # 字段说明：recipe_name
    # 作用：目标菜谱名称。
    # 类型：str。
    recipe_name: str
    # 字段说明：reason
    # 作用：规划或审核给出的理由说明。
    # 类型：str。
    reason: str
    # 字段说明：matched_terms
    # 作用：匹配成功的食材或词项，提供过滤与审核证据。
    # 类型：tuple[str, ...]。
    # 初始值：()。
    matched_terms: tuple[str, ...] = ()
    # 字段说明：evidence
    # 作用：当前任务可使用的证据。
    # 类型：ToolEvidence。
    evidence: ToolEvidence
