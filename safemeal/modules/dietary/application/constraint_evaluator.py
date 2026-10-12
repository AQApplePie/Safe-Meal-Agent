"""根据结构化菜谱证据确定性评估约束。"""

from safemeal.modules.dietary.contracts.control_plane import (
    ConstraintDecision,
    ToolEvidence,
)
from safemeal.shared.contracts.semantic import ConstraintStatement
from safemeal.modules.dietary.application.ingredient_terms import (
    INGREDIENT_ALIASES,
    SPICY_INGREDIENT_TERMS,
)
from safemeal.modules.dietary.application.recipe_safety import (
    match_forbidden_ingredients,
)


# 类说明（业务或基础设施实现类）：ConstraintEvaluator
# 作用：实现饮食约束校验器，封装该组件的业务处理与依赖协作。
class ConstraintEvaluator:
    # 方法说明：evaluate
    # 作用：根据可信约束审核菜谱的食材、安全性与适配程度。
    # 入参：
    #   constraint（ConstraintStatement）：当前饮食硬约束。
    #   evidence（ToolEvidence）：当前任务可使用的证据。
    # 出参：ConstraintDecision；饮食约束执行决策。
    def evaluate(
        self, constraint: ConstraintStatement, evidence: ToolEvidence
    ) -> ConstraintDecision:
        forbidden: tuple[str, ...] = ()
        if constraint.value == "non_spicy":
            forbidden = SPICY_INGREDIENT_TERMS
        elif constraint.type in {"allergy", "restriction", "avoid"}:
            forbidden = tuple(
                INGREDIENT_ALIASES.get(constraint.value, [constraint.value])
            )
        if forbidden:
            matched = match_forbidden_ingredients(evidence.ingredients, forbidden)
            if matched:
                return ConstraintDecision(
                    status="violated",
                    constraint=constraint,
                    recipe_name=evidence.recipe_name,
                    reason="完整食材证据命中禁止项。",
                    matched_terms=matched,
                    evidence=evidence,
                )
            if not evidence.ingredients_complete or not evidence.source_complete:
                return ConstraintDecision(
                    status="unknown",
                    constraint=constraint,
                    recipe_name=evidence.recipe_name,
                    reason="食材证据不完整，无法确认约束。",
                    evidence=evidence,
                )
            return ConstraintDecision(
                status="satisfied",
                constraint=constraint,
                recipe_name=evidence.recipe_name,
                reason="完整食材证据未命中禁止项。",
                evidence=evidence,
            )
        return ConstraintDecision(
            status="unknown",
            constraint=constraint,
            recipe_name=evidence.recipe_name,
            reason="该约束尚无可执行的结构化证据规则。",
            evidence=evidence,
        )


__all__ = ["ConstraintEvaluator"]
