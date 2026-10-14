from decimal import Decimal

import pytest

from safemeal.modules.recipe.contracts.models import (
    CookingStep,
    Ingredient,
    IngredientQuantity,
    NutritionInfo,
    Recipe,
)
from safemeal.agent.runtime.tools.adapters.constraint_verification import (
    VerifyRecipeConstraintsTool,
)


def recipe() -> Recipe:
    nutrition = NutritionInfo()
    return Recipe(
        id=17,
        name="柠檬蒸三文鱼",
        total_time_minutes=20,
        servings=2,
        difficulty="easy",
        ingredients=(
            IngredientQuantity(
                ingredient=Ingredient(id=1, name="三文鱼", nutrition=nutrition),
                quantity=Decimal("280"),
                unit="g",
                is_main=True,
                ingredient_type="main",
            ),
            IngredientQuantity(
                ingredient=Ingredient(id=2, name="柠檬", nutrition=nutrition),
                quantity=Decimal("1"),
                unit="个",
                ingredient_type="auxiliary",
            ),
        ),
        steps=(CookingStep(number=1, action="蒸", instruction="蒸熟"),),
        nutrition=nutrition,
    )


@pytest.mark.asyncio
async def test_verify_recipe_constraints_returns_deterministic_decisions():
    class Recipes:
        def get(self, recipe_id):
            assert recipe_id == 17
            return recipe()

    result = await VerifyRecipeConstraintsTool(Recipes()).invoke(
        "verify-1",
        {
            "recipe_ids": [17],
            "constraints": [
                {
                    "type": "avoid",
                    "value": "花生",
                    "strength": "strong_requirement",
                }
            ],
        },
    )

    assert result.ok is True
    assert result.data["verified"] is True
    assert result.data["decisions"][0]["status"] == "satisfied"


@pytest.mark.asyncio
async def test_verify_recipe_constraints_fails_closed_on_violation():
    class Recipes:
        def get(self, recipe_id):
            return recipe()

    result = await VerifyRecipeConstraintsTool(Recipes()).invoke(
        "verify-2",
        {
            "recipe_ids": [17],
            "constraints": [
                {
                    "type": "allergy",
                    "value": "鱼",
                    "strength": "hard_safety",
                }
            ],
        },
    )

    assert result.ok is True
    assert result.data["verified"] is False
    assert result.data["decisions"][0]["status"] == "violated"


@pytest.mark.asyncio
async def test_verify_recipe_constraints_rejects_duplicate_recipe_ids():
    class Recipes:
        def get(self, recipe_id):
            return recipe()

    result = await VerifyRecipeConstraintsTool(Recipes()).invoke(
        "verify-duplicates",
        {
            "recipe_ids": [17, 17],
            "constraints": [
                {
                    "type": "avoid",
                    "value": "花生",
                    "strength": "strong_requirement",
                }
            ],
        },
    )

    assert result.ok is False
    assert result.status == "rejected"
    assert result.error_code == "invalid_tool_arguments"
