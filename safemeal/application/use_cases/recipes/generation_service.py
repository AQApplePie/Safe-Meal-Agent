"""Application service enforcing deterministic constraints on generated recipes."""

from safemeal.modules.recipe_catalog.generation import (
    GeneratedRecipe,
    RecipeGenerationRequest,
)
from safemeal.modules.recipe_catalog.policy import RecipePolicy
from safemeal.application.errors import ModelOutputValidationError
from safemeal.application.ports.recipe_generator import RecipeGenerator


class RecipeGenerationService:
    def __init__(self, generator: RecipeGenerator) -> None:
        self._generator = generator

    async def generate(self, request: RecipeGenerationRequest) -> GeneratedRecipe:
        recipe = await self._generator.generate_recipe(request)
        forbidden = tuple(
            request.exclude_ingredients
        ) + RecipePolicy.forbidden_terms_for(request.dietary_types)
        if forbidden and recipe.contains_any(forbidden):
            raise ModelOutputValidationError(
                "generated recipe violates ingredient constraints"
            )
        missing_required = [
            required
            for required in request.include_ingredients
            if not recipe.contains_any((required,))
        ]
        if missing_required:
            raise ModelOutputValidationError(
                "generated recipe omitted required ingredients: "
                + ", ".join(missing_required)
            )
        if request.servings is not None and recipe.servings != request.servings:
            raise ModelOutputValidationError(
                "generated recipe servings do not match request"
            )
        if (
            request.max_total_time_minutes is not None
            and recipe.total_time_minutes > request.max_total_time_minutes
        ):
            raise ModelOutputValidationError(
                "generated recipe exceeds requested time limit"
            )
        return recipe


__all__ = ["RecipeGenerationService"]
