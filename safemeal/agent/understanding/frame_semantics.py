"""对结构合法的 RequestFrame 执行跨字段语义校验。"""

from __future__ import annotations

from safemeal.shared.contracts.request_frame import (
    ConstraintStatement,
    RequestFrame,
    ConstraintScope,
    RequestTask,
)
from safemeal.modules.recipe.application.food_category import canonical_food_category


# 类说明（业务或基础设施实现类）：RequestFrameSemanticValidator
# 作用：不重新解析用户原文，只归一化字段之间的冲突。
class RequestFrameSemanticValidator:
    """不重新解析用户原文，只归一化字段之间的冲突。"""

    # 方法说明：normalize
    # 作用：在请求语义框架业务校验器中归一化输入字段，统一后续处理格式。
    # 入参：
    #   frame（RequestFrame）：归一化请求语义框架。
    #   deterministic（RequestFrame | None）：当前规则路径的确定性判定结果；默认值为 None。
    # 出参：RequestFrame；归一化请求语义框架。
    def normalize(
        self,
        frame: RequestFrame,
        *,
        deterministic: RequestFrame | None = None,
    ) -> RequestFrame:
        errors = list(frame.validation_errors)
        categories = {
            item.value
            for item in frame.current_constraints
            if item.kind == "food_category"
        }
        preferences = list(frame.turn_preferences)
        current_constraints = tuple(
            item
            for item in frame.current_constraints
            if not (
                item.kind == "restriction"
                and canonical_food_category(item.value) in categories
            )
        )
        if categories:
            # 品类词表示分类体系，不要求原样出现在食材列表中。
            preferences = [
                item
                for item in preferences
                if not (
                    item.kind == "include_ingredient"
                    and canonical_food_category(item.value) in categories
                )
            ]

        excluded = {
            item.value for item in preferences if item.kind == "avoid_ingredient"
        }
        if excluded:
            preferences = [
                item
                for item in preferences
                if not (item.kind == "include_ingredient" and item.value in excluded)
            ]

        target = frame.target
        if (
            target.ingredient
            and canonical_food_category(target.ingredient) in categories
        ):
            target = target.model_copy(update={"ingredient": None})

        fields = frame.requested_fields
        tasks = frame.tasks
        exact = frame.exact_match_required
        status = frame.understanding_status
        clarification = frame.clarification_question
        if frame.primary_task == "recipe_detail":
            if not target.recipe_name and deterministic is not None:
                target = target.model_copy(
                    update={"recipe_name": deterministic.target.recipe_name}
                )
            if not fields and deterministic is not None:
                fields = deterministic.requested_fields
            if not target.recipe_name:
                errors.append("recipe_detail_target_missing")
            if not fields:
                errors.append("recipe_detail_fields_missing")
            if not target.recipe_name or not fields:
                tasks = (RequestTask(kind="clarify"),)
                exact = False
                status = "incomplete"
                clarification = "请告诉我具体菜名，以及想了解材料、步骤、时间还是营养。"
            else:
                exact = True
        elif fields:
            errors.append("requested_fields_without_recipe_detail")
            fields = ()

        statements = list(frame.statements)
        if not statements:
            scope: ConstraintScope = (
                "current_meal"
                if frame.primary_task == "menu_planning"
                else "current_turn"
            )
            for item in current_constraints:
                statements.append(
                    ConstraintStatement(
                        type=item.kind,
                        value=item.value,
                        strength=(
                            "hard_safety"
                            if item.kind == "allergy"
                            else "strong_requirement"
                            if item.kind in {"restriction", "avoid_food_category"}
                            else "menu_goal"
                        ),
                        scope=scope,
                    )
                )
            for preference in preferences:
                if preference.kind == "other":
                    continue
                statements.append(
                    ConstraintStatement(
                        type=(
                            "avoid"
                            if preference.kind == "avoid_ingredient"
                            else "include"
                            if preference.kind == "include_ingredient"
                            else preference.kind
                        ),
                        value=(
                            "non_spicy"
                            if preference.kind == "taste" and preference.value == "不辣"
                            else preference.value
                        ),
                        strength=(
                            "strong_requirement"
                            if preference.required
                            else "menu_goal"
                            if preference.kind == "include_ingredient"
                            else "soft_preference"
                        ),
                        scope=scope,
                    )
                )

        return frame.model_copy(
            update={
                "tasks": tasks,
                "turn_preferences": tuple(preferences),
                "current_constraints": current_constraints,
                "target": target,
                "requested_fields": fields,
                "exact_match_required": exact,
                "understanding_status": status,
                "clarification_question": clarification,
                "validation_errors": tuple(dict.fromkeys(errors)),
                "canonical": True,
                "statements": tuple(dict.fromkeys(statements)),
            }
        )


__all__ = ["RequestFrameSemanticValidator"]
