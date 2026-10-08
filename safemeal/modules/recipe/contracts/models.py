"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=Decimal("0"))]


class RecipeDifficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class DietaryType(str, Enum):
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"
    PESCATARIAN = "pescatarian"


class UnitDimension(str, Enum):
    MASS = "mass"
    VOLUME = "volume"
    COUNT = "count"


class NormalizedQuantity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: Decimal = Field(gt=0)
    unit: str
    dimension: UnitDimension


_UNIT_ALIASES = {
    "克": "g",
    "公克": "g",
    "千克": "kg",
    "公斤": "kg",
    "毫升": "ml",
    "升": "l",
    "大匙": "汤匙",
    "tbsp": "汤匙",
    "茶匙": "茶匙",
    "tsp": "茶匙",
}
_UNIT_DEFINITIONS: dict[str, tuple[UnitDimension, Decimal, str]] = {
    "mg": (UnitDimension.MASS, Decimal("0.001"), "g"),
    "g": (UnitDimension.MASS, Decimal("1"), "g"),
    "kg": (UnitDimension.MASS, Decimal("1000"), "g"),
    "ml": (UnitDimension.VOLUME, Decimal("1"), "ml"),
    "l": (UnitDimension.VOLUME, Decimal("1000"), "ml"),
    "茶匙": (UnitDimension.VOLUME, Decimal("5"), "ml"),
    "汤匙": (UnitDimension.VOLUME, Decimal("15"), "ml"),
    "个": (UnitDimension.COUNT, Decimal("1"), "个"),
    "条": (UnitDimension.COUNT, Decimal("1"), "条"),
}


def normalize_quantity(value: Decimal | str | int, unit: str) -> NormalizedQuantity:

    try:
        quantity = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError("ingredient quantity must be numeric") from exc
    normalized_unit = _UNIT_ALIASES.get(
        unit.strip().casefold(), unit.strip().casefold()
    )
    definition = _UNIT_DEFINITIONS.get(normalized_unit)
    if definition is None:
        raise ValueError(f"unsupported ingredient unit: {unit}")
    dimension, factor, canonical_unit = definition
    return NormalizedQuantity(
        value=quantity * factor,
        unit=canonical_unit,
        dimension=dimension,
    )


class NutritionInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    calories: NonNegativeDecimal = Decimal("0")
    protein_g: NonNegativeDecimal = Decimal("0")
    carbs_g: NonNegativeDecimal = Decimal("0")
    fat_g: NonNegativeDecimal = Decimal("0")
    basis: Literal["per_recipe", "per_100g"] = "per_recipe"

    @model_validator(mode="after")
    def validate_plausible_boundaries(self) -> "NutritionInfo":
        if self.calories > Decimal("100000"):
            raise ValueError("calories exceed the supported recipe boundary")
        if any(
            value > Decimal("10000")
            for value in (self.protein_g, self.carbs_g, self.fat_g)
        ):
            raise ValueError("macronutrients exceed the supported recipe boundary")
        return self


class Ingredient(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int = Field(gt=0)
    name: NonBlankText
    category: str | None = None
    nutrition: NutritionInfo


class IngredientQuantity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ingredient: Ingredient
    quantity: Decimal = Field(gt=0)
    unit: NonBlankText
    normalized: NormalizedQuantity
    preparation: str | None = None
    is_main: bool = False
    ingredient_type: Literal["main", "auxiliary", "seasoning"]

    @model_validator(mode="before")
    @classmethod
    def populate_normalized_quantity(cls, data: object) -> object:
        if isinstance(data, dict) and data.get("normalized") is None:
            data = dict(data)
            data["normalized"] = normalize_quantity(data["quantity"], str(data["unit"]))
        return data


class CookingStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    number: int = Field(ge=1)
    action: NonBlankText
    instruction: NonBlankText
    duration_minutes: int = Field(default=0, ge=0, le=24 * 60)
    temperature: str | None = None
    tips: str | None = None


class Recipe(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int = Field(gt=0)
    name: NonBlankText
    description: str | None = None
    total_time_minutes: int = Field(ge=0, le=7 * 24 * 60)
    servings: int = Field(gt=0, le=1000)
    difficulty: RecipeDifficulty
    cuisine: str | None = None
    taste: str | None = Field(
        default=None, max_length=100, description="明确的口味标注；未知时不填。"
    )
    equipment: tuple[str, ...] | None = Field(
        default=None, max_length=20, description="完成全部步骤需要的设备；未知时不填。"
    )
    ingredients: tuple[IngredientQuantity, ...] = Field(min_length=1)
    steps: tuple[CookingStep, ...] = Field(min_length=1)
    nutrition: NutritionInfo

    @model_validator(mode="after")
    def validate_aggregate_invariants(self) -> "Recipe":
        ingredient_ids = [item.ingredient.id for item in self.ingredients]
        if len(ingredient_ids) != len(set(ingredient_ids)):
            raise ValueError("recipe contains duplicate ingredients")
        step_numbers = [step.number for step in self.steps]
        if step_numbers != list(range(1, len(step_numbers) + 1)):
            raise ValueError("recipe steps must be ordered and contiguous from 1")
        return self


__all__ = [
    "CookingStep",
    "DietaryType",
    "Ingredient",
    "IngredientQuantity",
    "NormalizedQuantity",
    "NutritionInfo",
    "Recipe",
    "RecipeDifficulty",
    "UnitDimension",
    "normalize_quantity",
]
