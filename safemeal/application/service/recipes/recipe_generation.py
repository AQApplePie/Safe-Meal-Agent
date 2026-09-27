"""Application service enforcing deterministic constraints on generated recipes."""

from safemeal.application.contracts.recipes.generation import RecipeGenerationRequest
from safemeal.modules.recipe_catalog.generated_recipe import GeneratedRecipe
from safemeal.modules.dietary_safety.generated_safety import generated_recipe_violations
from safemeal.modules.recipe_catalog.dietary_filter import DietaryRecipeFilter
from safemeal.application.exceptions import ModelOutputValidationError
from safemeal.application.ports.llm.language_model_gateway import LanguageModelGateway


class RecipeGenerationService:
    def __init__(self, model_gateway: LanguageModelGateway) -> None:
        self._model_gateway = model_gateway

    async def generate_recipe(
        self, request: RecipeGenerationRequest
    ) -> GeneratedRecipe:
        recipe = await self._model_gateway.generate_recipe(request)
        forbidden = tuple(
            request.exclude_ingredients
        ) + DietaryRecipeFilter.excluded_terms_for(request.dietary_types)
        if forbidden and generated_recipe_violations(recipe, forbidden):
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
