"""饮食安全数据类型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


# 类说明（枚举类）：SafetyStatus
# 作用：限定食谱安全审核状态枚举的允许取值，统一业务分支判定。
class SafetyStatus(str, Enum):
    # 字段说明：SAFE
    # 作用：安全审核通过。
    # 初始值：'safe'。
    # 取值说明：
    #   safe：安全审核通过。
    SAFE = "safe"
    # 字段说明：UNSAFE
    # 作用：因条件不满足而排除。
    # 初始值：'excluded'。
    # 取值说明：
    #   excluded：因条件不满足而排除。
    UNSAFE = "excluded"
    # 字段说明：UNKNOWN
    # 作用：证据不足，无法作出确定结论。
    # 初始值：'unknown'。
    # 取值说明：
    #   unknown：证据不足，无法作出确定结论。
    UNKNOWN = "unknown"


# 类说明（数据契约类）：Ingredient
# 作用：描述菜谱食材条目的结构、类型及可校验字段。
@dataclass(frozen=True, slots=True)
class Ingredient:
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 类型：str。
    name: str


# 类说明（数据契约类）：Evidence
# 作用：描述单条请求证据的结构、类型及可校验字段。
@dataclass(frozen=True, slots=True)
class Evidence:
    # 字段说明：source
    # 作用：安全判断依据的来源标识。
    # 类型：str。
    source: str
    # 字段说明：reference
    # 作用：当前结果引用的来源或历史对象。
    # 类型：str。
    # 初始值：''。
    reference: str = ""


# 类说明（数据契约类）：EvidenceBundle
# 作用：描述请求证据集合的结构、类型及可校验字段。
@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    # 字段说明：items
    # 作用：当前处理的条目集合。
    # 类型：tuple[Evidence, ...]。
    # 初始值：()。
    items: tuple[Evidence, ...] = ()
    # 字段说明：ingredients_complete
    # 作用：食材清单是否完整，缺失时不能给出确定的安全结论。
    # 类型：bool。
    # 初始值：False。
    ingredients_complete: bool = False
    # 字段说明：core_source_available
    # 作用：核心可信数据源是否可用，用于决定降级与结果可信度。
    # 类型：bool。
    # 初始值：True。
    core_source_available: bool = True
    # 字段说明：conflicting_sources
    # 作用：提供相互冲突事实的来源标识集合。
    # 类型：tuple[str, ...]。
    # 初始值：()。
    conflicting_sources: tuple[str, ...] = ()


# 类说明（数据契约类）：SafetyRisk
# 作用：描述食谱安全风险枚举的结构、类型及可校验字段。
@dataclass(frozen=True, slots=True)
class SafetyRisk:
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 类型：str。
    code: str
    # 字段说明：detail
    # 作用：结果、错误或诊断的补充明细。
    # 类型：str。
    detail: str


# 类说明（数据契约类）：RecipeSafetyInput
# 作用：描述食谱安全审核输入的结构、类型及可校验字段。
@dataclass(frozen=True, slots=True)
class RecipeSafetyInput:
    # 字段说明：recipe_name
    # 作用：目标菜谱名称。
    # 类型：str。
    recipe_name: str
    # 字段说明：ingredients
    # 作用：菜谱使用的完整食材集合。
    # 类型：tuple[Ingredient, ...]。
    ingredients: tuple[Ingredient, ...]
    # 字段说明：forbidden_terms
    # 作用：禁止词项及其规范化集合。
    # 类型：tuple[str, ...]。
    forbidden_terms: tuple[str, ...]
    # 字段说明：evidence
    # 作用：当前任务可使用的证据。
    # 类型：EvidenceBundle。
    evidence: EvidenceBundle


# 类说明（数据契约类）：SafetyDecision
# 作用：描述本轮饮食安全决策的结构、类型及可校验字段。
@dataclass(frozen=True, slots=True)
class SafetyDecision:
    # 字段说明：status
    # 作用：HTTP 状态码或业务状态。
    # 类型：SafetyStatus。
    # 补充取值说明（类型别名或枚举）：
    #   safe：安全审核通过。
    #   excluded：因条件不满足而排除。
    #   unknown：证据不足，无法作出确定结论。
    status: SafetyStatus
    # 字段说明：risks
    # 作用：资料或安全评估指出的潜在风险说明。
    # 类型：tuple[SafetyRisk, ...]。
    # 初始值：()。
    risks: tuple[SafetyRisk, ...] = ()
    # 字段说明：matched_ingredients
    # 作用：匹配成功的食材或词项，提供过滤与审核证据。
    # 类型：tuple[str, ...]。
    # 初始值：()。
    matched_ingredients: tuple[str, ...] = ()
    # 字段说明：reason
    # 作用：规划或审核给出的理由说明。
    # 类型：str。
    # 初始值：''。
    reason: str = ""

    # 方法说明：eligible
    # 作用：判断当前状态是否允许继续执行指定动作。
    # 入参：
    #   无显式入参。
    # 出参：bool；当前状态与预算是否允许该动作。
    @property
    def eligible(self) -> bool:

        return self.status is SafetyStatus.SAFE
