"""Port for schema-constrained model recipe generation."""

from typing import Protocol

from safemeal.modules.recipe_catalog.generation import (
    GeneratedRecipe,
    RecipeGenerationRequest,
)


class RecipeGenerator(Protocol):
    async def generate_recipe(
        self, request: RecipeGenerationRequest
    ) -> GeneratedRecipe: ...


__all__ = ["RecipeGenerator"]
