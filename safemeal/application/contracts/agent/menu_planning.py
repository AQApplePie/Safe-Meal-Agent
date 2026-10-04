"""Serializable execution state for composite menu-planning tasks."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from safemeal.application.contracts.workflow.request_frame import (
    MenuCategory,
    MenuPlanningRequirements,
)
from safemeal.shared.types import JsonObject


class MenuExecutionPlan(BaseModel):
    """Stable goal copied from RequestFrame into the Agent checkpoint state."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    scenario: str | None = None
    required: dict[MenuCategory, int]
    distinct_recipes: bool = True
    allow_cross_category_counting: bool = False


class SelectedMenuRecipe(BaseModel):
    """One selected candidate and the quota slot it occupies."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    recipe_id: int | None = None
    name: str = Field(min_length=1, max_length=255)
    assigned_category: MenuCategory
    categories: tuple[MenuCategory, ...]
    credited_categories: tuple[MenuCategory, ...] = ()
    main_ingredients: tuple[str, ...] = ()
    evidence_call_id: str


class MenuTaskProgress(BaseModel):
    """Deterministic cumulative progress persisted between Agent iterations."""

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
    """Create a checkpoint-safe plan and zeroed progress from accepted quotas."""

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
