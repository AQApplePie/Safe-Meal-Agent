"""根据完整食材证据判定单个菜谱的安全状态。"""

from __future__ import annotations

from safemeal.modules.dietary.contracts.models import (
    SafetyStatus,
    EvidenceBundle,
    SafetyRisk,
    RecipeSafetyInput,
    SafetyDecision,
)

from typing import Iterable

from safemeal.modules.dietary.application.ingredient_terms import (
    DERIVED_SUFFIXES,
    NORMALISE_REMOVE_PATTERN,
    PREPARATION_PREFIXES,
    TOO_BROAD_TERMS,
)


# 方法说明：_unique
# 作用：保持输入顺序去重并清理空值。
# 入参：
#   items（Iterable[str]）：当前处理的条目集合。
# 出参：tuple[str, ...]；保持原输入顺序的非空去重条目集合。
def _unique(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in items if item.strip()))


# 方法说明：normalize_ingredient_name
# 作用：归一化食材名称或词项，统一安全匹配依据。
# 入参：
#   value（str）：当前待转换或校验的值。
# 出参：str；文本字符串。
def normalize_ingredient_name(value: str) -> str:

    return NORMALISE_REMOVE_PATTERN.sub("", str(value).strip().casefold())


# 方法说明：ingredient_matches_forbidden_term
# 作用：判断食材是否命中禁止词、别名或食材类别。
# 入参：
#   ingredient（str）：当前食材条目。
#   term（str）：待规范化或匹配的食材词项。
# 出参：bool；目标食材或菜谱是否满足当前分类或禁止词匹配规则。
def ingredient_matches_forbidden_term(ingredient: str, term: str) -> bool:

    ingredient_name = normalize_ingredient_name(ingredient)
    forbidden = normalize_ingredient_name(term)
    if not ingredient_name or not forbidden:
        return False
    if ingredient_name == forbidden:
        return True
    if ingredient_name.endswith(forbidden):
        prefix = ingredient_name[: -len(forbidden)]
        return not prefix or prefix in PREPARATION_PREFIXES
    if ingredient_name.startswith(forbidden):
        suffix = ingredient_name[len(forbidden) :]
        return suffix in DERIVED_SUFFIXES
    if forbidden in TOO_BROAD_TERMS:
        return False
    return False


# 方法说明：match_forbidden_ingredients
# 作用：找出候选食材中命中的禁止食材及匹配依据。
# 入参：
#   ingredients（Iterable[str]）：菜谱使用的完整食材集合。
#   forbidden_terms（Iterable[str]）：禁止词项及其规范化集合。
# 出参：tuple[str, ...]；实际命中的禁止食材名称元组。
def match_forbidden_ingredients(
    ingredients: Iterable[str], forbidden_terms: Iterable[str]
) -> tuple[str, ...]:

    terms = tuple(forbidden_terms)
    return _unique(
        ingredient
        for ingredient in ingredients
        if any(ingredient_matches_forbidden_term(ingredient, term) for term in terms)
    )


# 方法说明：has_sufficient_evidence
# 作用：判断现有观察是否足以支撑当前任务回答。
# 入参：
#   bundle（EvidenceBundle）：本次使用的提示词或证据集合。
# 出参：bool；当前证据是否已经足以完成任务。
def has_sufficient_evidence(bundle: EvidenceBundle) -> bool:

    return (
        bundle.core_source_available
        and bundle.ingredients_complete
        and bool(bundle.items)
    )


# 方法说明：has_conflicting_evidence
# 作用：判断当前证据是否相互冲突而不能直接形成答案。
# 入参：
#   bundle（EvidenceBundle）：本次使用的提示词或证据集合。
# 出参：bool；现有证据是否存在冲突。
def has_conflicting_evidence(bundle: EvidenceBundle) -> bool:

    return bool(bundle.conflicting_sources)


# 类说明（业务或基础设施实现类）：RecipeSafetyEvaluator
# 作用：实现食谱确定性安全审核器，封装该组件的业务处理与依赖协作。
class RecipeSafetyEvaluator:
    # 方法说明：evaluate
    # 作用：根据可信约束审核菜谱的食材、安全性与适配程度。
    # 入参：
    #   safety_input（RecipeSafetyInput）：包含菜谱证据与硬约束的安全审核输入。
    # 出参：SafetyDecision；本轮饮食安全决策。
    def evaluate(self, safety_input: RecipeSafetyInput) -> SafetyDecision:
        matched = match_forbidden_ingredients(
            (item.name for item in safety_input.ingredients),
            safety_input.forbidden_terms,
        )
        if matched:
            return SafetyDecision(
                status=SafetyStatus.UNSAFE,
                risks=(
                    SafetyRisk(
                        code="forbidden_ingredient",
                        detail="、".join(matched),
                    ),
                ),
                matched_ingredients=matched,
                reason="候选菜证据中命中忌口/过敏食材，不能推荐。",
            )
        if not safety_input.evidence.core_source_available:
            return SafetyDecision(
                status=SafetyStatus.UNKNOWN,
                risks=(SafetyRisk("core_source_unavailable", "核心安全数据不可用"),),
                reason="核心安全数据不可用，按 fail-closed 处理。",
            )
        if has_conflicting_evidence(safety_input.evidence):
            return SafetyDecision(
                status=SafetyStatus.UNKNOWN,
                risks=(SafetyRisk("evidence_conflict", "安全证据相互冲突"),),
                reason="安全证据存在冲突，不能确认安全。",
            )
        if not has_sufficient_evidence(safety_input.evidence):
            return SafetyDecision(
                status=SafetyStatus.UNKNOWN,
                risks=(SafetyRisk("insufficient_evidence", "食材证据不完整"),),
                reason="候选菜缺少完整食材证据，不能确认安全。",
            )
        return SafetyDecision(
            status=SafetyStatus.SAFE,
            reason="候选菜的结构化食材证据未命中忌口/过敏食材。",
        )


__all__ = [
    "RecipeSafetyEvaluator",
    "has_conflicting_evidence",
    "has_sufficient_evidence",
    "ingredient_matches_forbidden_term",
    "match_forbidden_ingredients",
    "normalize_ingredient_name",
]
