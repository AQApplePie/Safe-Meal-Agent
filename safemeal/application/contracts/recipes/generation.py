"""Application request contract for AI recipe generation."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from safemeal.application.contracts.recipes.models import DietaryType


class RecipeGenerationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    requirements: str = Field(min_length=1, max_length=5000)
    include_ingredients: tuple[str, ...] = Field(default_factory=tuple, max_length=20)
    exclude_ingredients: tuple[str, ...] = Field(default_factory=tuple, max_length=50)
    dietary_types: tuple[DietaryType, ...] = Field(default_factory=tuple, max_length=3)
    servings: int | None = Field(default=None, ge=1, le=100)
    max_total_time_minutes: int | None = Field(default=None, ge=1, le=24 * 60)

    @field_validator("include_ingredients", "exclude_ingredients", mode="before")
    @classmethod
    def normalize_ingredient_terms(cls, value: object) -> object:
        if value is None:
            return ()
        if not isinstance(value, (list, tuple, set)):
            raise ValueError("ingredient constraints must be a list or tuple")
        return tuple(
            dict.fromkeys(str(item).strip() for item in value if str(item).strip())
        )


__all__ = ["RecipeGenerationRequest"]
