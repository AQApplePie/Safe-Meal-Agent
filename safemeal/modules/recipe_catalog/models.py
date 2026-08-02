"""Stable recipe read models and deterministic validation rules."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
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


class RecipeSortField(str, Enum):
    NAME = "name"
    TOTAL_TIME = "total_time"
    CALORIES = "total_calories"


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
    """Normalize supported units without guessing density or count equivalence."""

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
    sort_by: RecipeSortField = RecipeSortField.NAME
    sort_order: Literal["asc", "desc"] = "asc"
    offset: int = Field(default=0, ge=0, le=100000)
    limit: int = Field(default=10, ge=1, le=50)

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

    items: tuple[Recipe, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)


__all__ = [
    "CookingStep",
    "DietaryType",
    "Ingredient",
    "IngredientQuantity",
    "NormalizedQuantity",
    "NutritionInfo",
    "Recipe",
    "RecipeDifficulty",
    "RecipeQuery",
    "RecipeSearchResult",
    "RecipeSortField",
    "UnitDimension",
    "normalize_quantity",
]
