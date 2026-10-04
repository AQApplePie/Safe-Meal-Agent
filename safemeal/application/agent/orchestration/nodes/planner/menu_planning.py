"""Batch planning strategy for composite menus inside the existing Planner node."""

from __future__ import annotations

from safemeal.application.contracts.agent.decisions import ToolCall
from safemeal.application.contracts.agent.menu_planning import (
    MenuExecutionPlan,
    MenuTaskProgress,
)


MAX_MENU_CALLS_PER_BATCH = 4
MENU_CANDIDATE_OVERSAMPLE = 2
MENU_MIN_CANDIDATES_PER_CATEGORY = 5


def build_menu_search_plan(
    plan_payload: dict,
    progress_payload: dict,
) -> list[ToolCall]:
    """Plan one batched search per unfinished quota, bounded by graph call limits."""

    plan = MenuExecutionPlan.model_validate(plan_payload)
    progress = MenuTaskProgress.model_validate(progress_payload)
    selected_ids = [
        item.recipe_id for item in progress.selected_recipes if item.recipe_id is not None
    ]
    selected_names = [item.name for item in progress.selected_recipes]
    unfinished = [
        (category, progress.remaining.get(category, required))
        for category, required in plan.required.items()
        if progress.remaining.get(category, required) > 0
        and category not in progress.exhausted_categories
    ]
    # Larger deficits go first; stable category order makes checkpoint retries
    # reproducible while still adapting every batch to current progress.
    unfinished.sort(key=lambda item: -item[1])
    calls: list[ToolCall] = []
    for category, remaining in unfinished[:MAX_MENU_CALLS_PER_BATCH]:
        attempt = progress.attempted_categories.get(category, 0) + 1
        limit = max(
            MENU_MIN_CANDIDATES_PER_CATEGORY,
            remaining * MENU_CANDIDATE_OVERSAMPLE,
        )
        calls.append(
            ToolCall(
                id=f"menu-{category}-{attempt}",
                tool_name="search_recipes",
                arguments={
                    "category": category,
                    "candidate_mode": True,
                    "limit": limit,
                    "exclude_recipe_ids": selected_ids,
                    "exclude_recipe_names": selected_names,
                    "scope": "local" if attempt == 1 else "all",
                },
                purpose=f"为菜单的 {category} 配额批量召回候选菜。",
                success_criteria=(
                    f"返回至少 {remaining} 道未重复且通过硬约束的 {category} 候选。"
                ),
            )
        )
    return calls


__all__ = [
    "MAX_MENU_CALLS_PER_BATCH",
    "MENU_CANDIDATE_OVERSAMPLE",
    "MENU_MIN_CANDIDATES_PER_CATEGORY",
    "build_menu_search_plan",
]
