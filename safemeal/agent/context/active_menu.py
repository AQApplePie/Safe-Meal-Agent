"""维护跨轮对话中的活动菜单状态。"""

from __future__ import annotations

from collections.abc import Mapping

from safemeal.agent.contracts.menu_planning import (
    MenuExecutionPlan,
    MenuTaskProgress,
)
from safemeal.agent.runtime.menu_coverage import (
    calculate_menu_coverage,
)
from safemeal.shared.types import JsonObject, to_json_object


# 方法说明：merge_active_menu_replacement
# 作用：将一个分类的替换结果合并到原菜单，并统一重算完整菜单配额。
# 入参：
#   previous_active（Mapping[str, object]）：此前状态或已有活动记录。
#   replacement_plan_payload（Mapping[str, object]）：局部替换产生的新菜单计划载荷。
#   replacement_progress_payload（Mapping[str, object]）：局部替换产生的新菜单进度载荷。
#   modification（Mapping[str, object]）：局部菜单替换要求。
# 出参：JsonObject；JSON 字段映射。
def merge_active_menu_replacement(
    previous_active: Mapping[str, object],
    replacement_plan_payload: Mapping[str, object],
    replacement_progress_payload: Mapping[str, object],
    modification: Mapping[str, object],
) -> JsonObject:
    """将一个分类的替换结果合并到原菜单，并统一重算完整菜单配额。"""

    previous_plan = MenuExecutionPlan.model_validate(previous_active.get("plan") or {})
    previous_progress = MenuTaskProgress.model_validate(
        previous_active.get("progress") or {}
    )
    replacement_plan = MenuExecutionPlan.model_validate(replacement_plan_payload)
    replacement_progress = MenuTaskProgress.model_validate(replacement_progress_payload)
    category = str(modification.get("target_category") or "")
    if category not in replacement_plan.required:
        raise ValueError("替换分类与本轮菜单计划不一致")

    required = dict(previous_plan.required)
    if not modification.get("partial"):
        required[category] = replacement_plan.required[category]  # type: ignore[index]
    merged_plan = previous_plan.model_copy(update={"required": required})
    replaced_payload = modification.get("replaced_recipe_names")
    replaced_names = (
        [name for name in replaced_payload if isinstance(name, str)]
        if isinstance(replaced_payload, list)
        else []
    )
    preserved = tuple(
        recipe
        for recipe in previous_progress.selected_recipes
        if (
            recipe.name not in replaced_names
            if modification.get("partial")
            else recipe.assigned_category != category
        )
    )
    selected = (*preserved, *replacement_progress.selected_recipes)
    fulfilled, remaining, complete = calculate_menu_coverage(merged_plan, selected)
    merged_progress = previous_progress.model_copy(
        update={
            "selected_recipes": selected,
            "fulfilled": fulfilled,
            "remaining": remaining,
            "complete": complete,
            "partial_reason": replacement_progress.partial_reason,
            "candidate_pool": (
                *previous_progress.candidate_pool,
                *replacement_progress.candidate_pool,
            ),
        }
    )
    return {
        "plan": to_json_object(merged_plan),
        "progress": to_json_object(merged_progress),
    }


__all__ = ["merge_active_menu_replacement"]
