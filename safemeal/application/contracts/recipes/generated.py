"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from safemeal.application.contracts.recipes.models import (
    DietaryType,
    NonBlankText,
    NutritionInfo,
    RecipeDifficulty,
    normalize_quantity,
)


GeneratedUnit = Literal["mg", "g", "kg", "ml", "l", "茶匙", "汤匙", "个", "条"]


class GeneratedIngredient(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: NonBlankText
    quantity: Decimal = Field(gt=0)
    unit: GeneratedUnit
    preparation: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_quantity_unit(self) -> "GeneratedIngredient":
        normalize_quantity(self.quantity, self.unit)
        return self


class GeneratedCookingStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    number: int = Field(ge=1)
    action: NonBlankText
    instruction: NonBlankText
    duration_minutes: int = Field(default=0, ge=0, le=24 * 60)
    temperature: str | None = Field(default=None, max_length=100)
    tips: str | None = Field(default=None, max_length=1000)


class GeneratedRecipe(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: NonBlankText
    description: str = Field(min_length=1, max_length=2000)
    total_time_minutes: int = Field(ge=1, le=24 * 60)
    servings: int = Field(ge=1, le=100)
    difficulty: RecipeDifficulty
    cuisine: str | None = Field(default=None, max_length=255)
    taste: str | None = Field(
        default=None, max_length=100, description="明确的口味标注；未知时不填。"
    )
    equipment: tuple[str, ...] | None = Field(
        default=None, max_length=20, description="完成全部步骤需要的设备；未知时不填。"
    )
    ingredients: tuple[GeneratedIngredient, ...] = Field(min_length=1, max_length=100)
    steps: tuple[GeneratedCookingStep, ...] = Field(min_length=1, max_length=100)
    nutrition: NutritionInfo
    allergens: tuple[str, ...] = Field(default_factory=tuple, max_length=50)
    dietary_types: tuple[DietaryType, ...] = Field(default_factory=tuple, max_length=3)

    @model_validator(mode="after")
    def validate_recipe_shape(self) -> "GeneratedRecipe":
        names = [item.name.casefold() for item in self.ingredients]
        if len(names) != len(set(names)):
            raise ValueError("generated recipe contains duplicate ingredients")
        numbers = [step.number for step in self.steps]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError("generated recipe steps must be contiguous from 1")
        return self


__all__ = [
    "GeneratedCookingStep",
    "GeneratedIngredient",
    "GeneratedRecipe",
    "GeneratedUnit",
]
