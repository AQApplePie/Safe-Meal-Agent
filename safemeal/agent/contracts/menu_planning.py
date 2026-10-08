"""复杂菜单规划任务的可序列化执行状态。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from safemeal.shared.contracts.request_frame import (
    MenuCategory,
    MenuPlanningRequirements,
)
from safemeal.shared.types import JsonObject


class MenuExecutionPlan(BaseModel):
    """从 RequestFrame 写入 Agent 检查点的稳定目标。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    scenario: str | None = None
    required: dict[MenuCategory, int]
    distinct_recipes: bool = True
    allow_cross_category_counting: bool = False


class SelectedMenuRecipe(BaseModel):
    """已选菜品及其占用的分类配额。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    recipe_id: int | None = None
    name: str = Field(min_length=1, max_length=255)
    assigned_category: MenuCategory
    categories: tuple[MenuCategory, ...]
    credited_categories: tuple[MenuCategory, ...] = ()
    main_ingredients: tuple[str, ...] = ()
    evidence_call_id: str


class MenuTaskProgress(BaseModel):
    """在 Agent 多次迭代之间持续保存的确定性进度。"""

    model_config = ConfigDict(extra="forbid")
    fulfilled: dict[MenuCategory, int]
    remaining: dict[MenuCategory, int]
    selected_recipes: tuple[SelectedMenuRecipe, ...] = ()
    candidate_pool: tuple[JsonObject, ...] = ()
    attempted_categories: dict[MenuCategory, int] = Field(default_factory=dict)
    exhausted_categories: tuple[MenuCategory, ...] = ()
    coverage_history: tuple[JsonObject, ...] = ()
    complete: bool = False
    partial_reason: str = ""
    excluded_recipe_ids: tuple[int, ...] = ()
    excluded_recipe_names: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_non_negative_counts(self) -> "MenuTaskProgress":
        counts = (*self.fulfilled.values(), *self.remaining.values())
        if any(value < 0 for value in counts):
            raise ValueError("menu progress counts cannot be negative")
        return self


def initialize_menu_task(
    requirements: MenuPlanningRequirements,
    *,
    scenario: str | None,
) -> tuple[MenuExecutionPlan, MenuTaskProgress]:
    """根据已确认配额创建计划和初始进度。"""

    required = {item.category: item.count for item in requirements.category_quotas}
    plan = MenuExecutionPlan(
        scenario=scenario,
        required=required,
        distinct_recipes=requirements.distinct_recipes,
        allow_cross_category_counting=requirements.allow_cross_category_counting,
    )
    progress = MenuTaskProgress(
        fulfilled={category: 0 for category in required},
        remaining=dict(required),
        attempted_categories={category: 0 for category in required},
    )
    return plan, progress


__all__ = [
    "MenuExecutionPlan",
    "MenuTaskProgress",
    "SelectedMenuRecipe",
    "initialize_menu_task",
]
