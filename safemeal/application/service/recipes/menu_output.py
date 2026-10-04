"""Chat-oriented rendering for deterministic menu-planning progress."""

from __future__ import annotations

from collections.abc import Collection

from safemeal.application.contracts.agent.menu_planning import (
    MenuExecutionPlan,
    MenuTaskProgress,
)
from safemeal.application.contracts.workflow.request_frame import MenuCategory
from safemeal.shared.types import JsonObject


CATEGORY_LABELS: dict[MenuCategory, str] = {
    "cold_dish": "凉菜",
    "hot_dish": "热菜",
    "vegetarian": "素菜",
    "meat": "荤菜",
    "soup": "汤",
    "staple": "主食",
}


def render_menu_plan(
    plan_payload: JsonObject,
    progress_payload: JsonObject,
    *,
    allowed_names: Collection[str] | None = None,
) -> str:
    """Render selected evidence by requested quota without exposing loop internals."""

    plan = MenuExecutionPlan.model_validate(plan_payload)
    progress = MenuTaskProgress.model_validate(progress_payload)
    allowed = set(allowed_names) if allowed_names is not None else None
    selected = [
        item
        for item in progress.selected_recipes
        if allowed is None or item.name in allowed
    ]
    lines = [
        f"按你的{plan.scenario or '用餐'}需求，我整理了下面这份菜单："
    ]
    missing: list[str] = []
    total_selected_names: set[str] = set()
    for category, required in plan.required.items():
        recipes = [
            item
            for item in selected
            if category in (item.credited_categories or (item.assigned_category,))
        ][:required]
        total_selected_names.update(item.name for item in recipes)
        label = CATEGORY_LABELS[category]
        lines.append(f"\n{label}（{len(recipes)}/{required}）")
        if recipes:
            for recipe in recipes:
                ingredients = "、".join(recipe.main_ingredients)
                lines.append(
                    f"- {recipe.name}（主要食材：{ingredients}）"
                    if ingredients
                    else f"- {recipe.name}"
                )
        else:
            lines.append("- 暂无经过核验的合适菜品")
        if len(recipes) < required:
            missing.append(f"{label}还缺 {required - len(recipes)} 道")

    if missing:
        reason = progress.partial_reason.strip()
        lines.append("\n当前是可确认的部分方案：" + "；".join(missing) + "。")
        if reason:
            lines.append(reason + "。")
    else:
        lines.append(
            f"\n共 {len(total_selected_names)} 道不同菜品，已按每类配额完成核验。"
        )
    return "\n".join(lines)


__all__ = ["CATEGORY_LABELS", "render_menu_plan"]
