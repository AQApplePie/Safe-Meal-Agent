"""统一计算菜单分类配额的完成情况。"""

from __future__ import annotations

from collections.abc import Iterable

from safemeal.agent.contracts.menu_planning import (
    MenuExecutionPlan,
    SelectedMenuRecipe,
)
from safemeal.shared.contracts.request_frame import MenuCategory


# 方法说明：calculate_menu_coverage
# 作用：根据同一套计数规则返回已完成、剩余和整体完成状态。
# 入参：
#   plan（MenuExecutionPlan）：本轮工具调用或菜单执行计划。
#   selected_recipes（Iterable[SelectedMenuRecipe]）：菜单中已经选定的菜品集合。
#   allowed_names（set[str] | None）：允许使用的名称集合；默认值为 None。
# 出参：tuple[dict[MenuCategory, int], dict[MenuCategory, int],
# bool]；菜单分类、整数组成的映射、菜单分类、整数组成的映射、布尔判定值组成的元组。
def calculate_menu_coverage(
    plan: MenuExecutionPlan,
    selected_recipes: Iterable[SelectedMenuRecipe],
    *,
    allowed_names: set[str] | None = None,
) -> tuple[dict[MenuCategory, int], dict[MenuCategory, int], bool]:
    """根据同一套计数规则返回已完成、剩余和整体完成状态。"""

    selected = tuple(
        recipe
        for recipe in selected_recipes
        if allowed_names is None or recipe.name in allowed_names
    )
    fulfilled = {
        category: sum(
            category in (recipe.credited_categories or (recipe.assigned_category,))
            for recipe in selected
        )
        for category in plan.required
    }
    remaining = {
        category: max(0, required - fulfilled[category])
        for category, required in plan.required.items()
    }
    return (
        fulfilled,
        remaining,
        bool(plan.required) and all(count == 0 for count in remaining.values()),
    )


__all__ = ["calculate_menu_coverage"]
