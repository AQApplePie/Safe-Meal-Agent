"""饮食安全数据类型。"""

from __future__ import annotations

from typing import List, Literal, Protocol
from pydantic import BaseModel, Field
from safemeal.shared.types import JsonObject


class DietaryEvidenceObservation(Protocol):
    """Minimal evidence shape consumed by dietary safety filtering."""

    call_id: str
    tool_name: str
    ok: bool
    data: object


class DietaryConstraint(BaseModel):
    """从用户问题中提取出的饮食安全约束。"""

    active: bool = Field(description="是否识别到忌口/过敏等饮食约束。")
    trigger_terms: List[str] = Field(default_factory=list, description="命中的触发词。")
    raw_ingredients: List[str] = Field(
        default_factory=list, description="用户原始提到的食材。"
    )
    excluded_ingredients: List[str] = Field(
        default_factory=list,
        description="展开后的禁忌食材或同义表达。",
    )
    strictness: str = Field(
        default="hard_exclusion",
        description="过滤严格度；过敏/忌口默认硬排除。",
    )


class RecipeSafetyRecord(BaseModel):
    """一道候选菜在忌口过滤后的分类结果。"""

    name: str = Field(description="菜名或候选项名称。")
    ingredients: List[str] = Field(
        default_factory=list, description="已确认的结构化食材。"
    )
    matched_forbidden_ingredients: List[str] = Field(
        default_factory=list,
        description="命中的禁忌食材表达。",
    )
    safety_status: Literal["safe", "excluded", "unknown"] = Field(
        default="unknown",
        description="安全分类：safe 可推荐，excluded 必须排除，unknown 证据不足。",
    )
    evidence_call_ids: List[str] = Field(
        default_factory=list,
        description="支持该判断的原始 Tool call_id。",
    )
    evidence: List[JsonObject] = Field(
        default_factory=list,
        description="来自工具或数据库的结构化证据片段。",
    )
    reason: str = Field(description="分类理由。")


class DietarySafetyResult(BaseModel):
    """一次确定性忌口过滤的完整输出。"""

    active: bool
    constraint: DietaryConstraint
    safe_recipes: List[RecipeSafetyRecord] = Field(default_factory=list)
    excluded_recipes: List[RecipeSafetyRecord] = Field(default_factory=list)
    unknown_recipes: List[RecipeSafetyRecord] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
