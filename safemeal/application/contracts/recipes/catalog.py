"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from safemeal.application.contracts.recipes.models import (
    DietaryType,
    Recipe,
    RecipeDifficulty,
)
from safemeal.application.contracts.recipes.lookup import RecipeCandidate
from safemeal.application.contracts.recipes.lookup import MenuRecipeCandidate
from safemeal.application.contracts.workflow.request_frame import MenuCategory

FoodCategory = Literal["fish", "seafood", "vegetarian"]


class RecipeSortField(str, Enum):
    NAME = "name"
    TOTAL_TIME = "total_time"
    CALORIES = "total_calories"


class RecipeQuery(BaseModel):

    model_config = ConfigDict(frozen=True, extra="forbid")

    name_contains: str | None = Field(default=None, min_length=1, max_length=255)
    include_ingredients: tuple[str, ...] = Field(default_factory=tuple, max_length=20)
    exclude_ingredients: tuple[str, ...] = Field(default_factory=tuple, max_length=50)
    difficulties: tuple[RecipeDifficulty, ...] = Field(
        default_factory=tuple, max_length=3
    )
    cuisine: str | None = Field(default=None, min_length=1, max_length=255)
    max_total_time_minutes: int | None = Field(default=None, ge=0, le=7 * 24 * 60)
    max_calories: Decimal | None = Field(default=None, ge=0, le=100000)
    dietary_types: tuple[DietaryType, ...] = Field(default_factory=tuple, max_length=3)
    food_categories: tuple[FoodCategory, ...] = Field(default_factory=tuple, max_length=3)
    exclude_food_categories: tuple[FoodCategory, ...] = Field(
        default_factory=tuple, max_length=3
    )
    sort_by: RecipeSortField = RecipeSortField.NAME
    sort_order: Literal["asc", "desc"] = "asc"
    offset: int = Field(default=0, ge=0, le=100000)
    limit: int = Field(default=10, ge=1, le=50)
    requested_count: int | None = Field(default=None, ge=1, le=50)


    candidate_limit: int | None = Field(default=None, ge=1, le=200)
    exact_name: bool = False
    required_fields: tuple[
        Literal["ingredients", "steps", "time", "nutrition"], ...
    ] = ()
    category: MenuCategory | None = None
    candidate_mode: bool = False
    exclude_recipe_ids: tuple[int, ...] = Field(default_factory=tuple, max_length=200)
    exclude_recipe_names: tuple[str, ...] = Field(default_factory=tuple, max_length=200)
    scope: Literal["local", "all"] = "local"

    @field_validator("include_ingredients", "exclude_ingredients", mode="before")
    @classmethod
    def normalize_terms(cls, value: object) -> object:
        if value is None:
            return ()
        if not isinstance(value, (list, tuple, set)):
            raise ValueError("ingredient filters must be a list or tuple")
        values = [str(item).strip() for item in value]
        return tuple(dict.fromkeys(item for item in values if item))


class RecipeSearchResult(BaseModel):

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[Recipe | RecipeCandidate | MenuRecipeCandidate, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
    status: Literal["FOUND", "PARTIAL", "NOT_FOUND", "ERROR", "FIELD_MISSING"] = "FOUND"
    requested_count: int | None = Field(default=None, ge=1, le=50)
    fulfilled_count: int | None = Field(default=None, ge=0, le=50)
    missing_fields: tuple[Literal["ingredients", "steps", "time", "nutrition"], ...] = ()
    query: str | None = None
    exact_name: bool = False
    match_type: Literal["exact", "normalized", "lexical", "none"] = "none"
    searched_sources: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


__all__ = ["RecipeQuery", "RecipeSearchResult", "RecipeSortField"]
