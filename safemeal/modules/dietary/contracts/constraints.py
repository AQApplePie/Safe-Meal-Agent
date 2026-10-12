"""饮食安全数据类型。"""

from __future__ import annotations

from typing import List, Literal, Protocol
from pydantic import BaseModel, Field
from safemeal.shared.types import JsonObject


# 类说明（接口类）：DietaryEvidenceObservation
# 作用：定义饮食证据观察的能力契约，供应用层与具体实现解耦。
class DietaryEvidenceObservation(Protocol):
    # 字段说明：call_id
    # 作用：工具调用标识。
    # 类型：str。
    call_id: str
    # 字段说明：tool_name
    # 作用：工具名称。
    # 类型：str。
    tool_name: str
    # 字段说明：ok
    # 作用：本次操作是否成功。
    # 类型：bool。
    ok: bool
    # 字段说明：data
    # 作用：饮食相关工具返回的原始业务载荷，供提取食材与约束证据。
    # 类型：object。
    data: object


# 类说明（数据契约类）：DietaryConstraint
# 作用：从用户问题中提取出的饮食安全约束。
class DietaryConstraint(BaseModel):
    """从用户问题中提取出的饮食安全约束。"""

    # 字段说明：active
    # 作用：是否识别到忌口/过敏等饮食约束。
    # 类型：bool。
    active: bool = Field(description="是否识别到忌口/过敏等饮食约束。")
    # 字段说明：trigger_terms
    # 作用：命中的触发词。
    # 类型：List[str]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    trigger_terms: List[str] = Field(default_factory=list, description="命中的触发词。")
    # 字段说明：raw_ingredients
    # 作用：用户原始提到的食材。
    # 类型：List[str]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    raw_ingredients: List[str] = Field(
        default_factory=list, description="用户原始提到的食材。"
    )
    # 字段说明：excluded_ingredients
    # 作用：展开后的禁忌食材或同义表达。
    # 类型：List[str]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    excluded_ingredients: List[str] = Field(
        default_factory=list,
        description="展开后的禁忌食材或同义表达。",
    )
    # 字段说明：strictness
    # 作用：过滤严格度；过敏/忌口默认硬排除。
    # 类型：str。
    # 配置：默认值='hard_exclusion'。
    strictness: str = Field(
        default="hard_exclusion",
        description="过滤严格度；过敏/忌口默认硬排除。",
    )


# 类说明（数据契约类）：RecipeSafetyRecord
# 作用：一道候选菜在忌口过滤后的分类结果。
class RecipeSafetyRecord(BaseModel):
    """一道候选菜在忌口过滤后的分类结果。"""

    # 字段说明：name
    # 作用：菜名或候选项名称。
    # 类型：str。
    name: str = Field(description="菜名或候选项名称。")
    # 字段说明：ingredients
    # 作用：已确认的结构化食材。
    # 类型：List[str]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    ingredients: List[str] = Field(
        default_factory=list, description="已确认的结构化食材。"
    )
    # 字段说明：matched_forbidden_ingredients
    # 作用：命中的禁忌食材表达。
    # 类型：List[str]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    matched_forbidden_ingredients: List[str] = Field(
        default_factory=list,
        description="命中的禁忌食材表达。",
    )
    # 字段说明：safety_status
    # 作用：安全分类：safe 可推荐，excluded 必须排除，unknown 证据不足。
    # 类型：Literal['safe', 'excluded', 'unknown']。
    # 配置：默认值='unknown'。
    # 取值说明：
    #   safe：安全审核通过。
    #   excluded：因条件不满足而排除。
    #   unknown：证据不足，无法作出确定结论。
    safety_status: Literal["safe", "excluded", "unknown"] = Field(
        default="unknown",
        description="安全分类：safe 可推荐，excluded 必须排除，unknown 证据不足。",
    )
    # 字段说明：evidence_call_ids
    # 作用：支持该判断的原始 Tool call_id。
    # 类型：List[str]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    evidence_call_ids: List[str] = Field(
        default_factory=list,
        description="支持该判断的原始 Tool call_id。",
    )
    # 字段说明：evidence
    # 作用：来自工具或数据库的结构化证据片段。
    # 类型：List[JsonObject]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    evidence: List[JsonObject] = Field(
        default_factory=list,
        description="来自工具或数据库的结构化证据片段。",
    )
    # 字段说明：reason
    # 作用：分类理由。
    # 类型：str。
    reason: str = Field(description="分类理由。")


# 类说明（数据契约类）：DietarySafetyResult
# 作用：一次确定性忌口过滤的完整输出。
class DietarySafetyResult(BaseModel):
    """一次确定性忌口过滤的完整输出。"""

    # 字段说明：active
    # 作用：该记录或约束是否处于生效状态。
    # 类型：bool。
    active: bool
    # 字段说明：constraint
    # 作用：当前饮食硬约束。
    # 类型：DietaryConstraint。
    constraint: DietaryConstraint
    # 字段说明：safe_recipes
    # 作用：审核后具有足够证据满足安全条件的菜谱。
    # 类型：List[RecipeSafetyRecord]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    safe_recipes: List[RecipeSafetyRecord] = Field(default_factory=list)
    # 字段说明：excluded_recipes
    # 作用：因约束不满足被移出结果的菜谱及相关记录。
    # 类型：List[RecipeSafetyRecord]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    excluded_recipes: List[RecipeSafetyRecord] = Field(default_factory=list)
    # 字段说明：unknown_recipes
    # 作用：食材或证据不完整、无法确定安全性的菜谱。
    # 类型：List[RecipeSafetyRecord]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    unknown_recipes: List[RecipeSafetyRecord] = Field(default_factory=list)
    # 字段说明：missing_information
    # 作用：当前任务尚缺少的信息集合。
    # 类型：List[str]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    missing_information: List[str] = Field(default_factory=list)
