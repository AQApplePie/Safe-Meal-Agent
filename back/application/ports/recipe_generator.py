"""Port for schema-constrained model recipe generation."""

from typing import Protocol

from SafeMealAgent.back.application.domain.recipe_generation import (
    GeneratedRecipe,
    RecipeGenerationRequest,
)


class RecipeGenerator(Protocol):
    async def generate_recipe(
        self, request: RecipeGenerationRequest
    ) -> GeneratedRecipe: ...


__all__ = ["RecipeGenerator"]
