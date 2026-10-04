"""Business food-category taxonomy, deliberately independent from allergy rules."""

from __future__ import annotations

from collections.abc import Iterable
from safemeal.application.contracts.recipes.catalog import FoodCategory

from safemeal.application.contracts.recipes.models import Recipe
from safemeal.application.service.recipes.classification import classify_recipe


_FISH = {
    "鱼", "鲈鱼", "海鲈", "黄鱼", "大黄鱼", "龙利鱼", "三文鱼", "鳕鱼",
    "鲤鱼", "草鱼", "鲫鱼", "银鱼", "带鱼", "鱼丸", "鱼柳",
}
_SHELLFISH = {
    "虾", "虾仁", "大虾", "海虾", "基围虾", "虾米", "蟹", "螃蟹",
    "蟹肉", "贝", "贝类", "扇贝", "扇贝肉", "蛤", "蛤蜊", "鱿鱼",
}
_ALIASES: dict[str, FoodCategory] = {
    "鱼": "fish",
    "鱼类": "fish",
    "海鲜": "seafood",
    "水产": "seafood",
    "素菜": "vegetarian",
    "素食": "vegetarian",
}


def canonical_food_category(value: str) -> FoodCategory | None:
    return _ALIASES.get(value.strip())


def _matches_member(ingredient: str, members: Iterable[str]) -> bool:
    value = ingredient.strip()
    return any(value == member or value.endswith(member) for member in members)


def recipe_matches_category(recipe: Recipe, category: FoodCategory) -> bool:
    """Classify by structured ingredients, never by a misleading recipe name."""

    ingredients = tuple(item.ingredient.name for item in recipe.ingredients)
    if category == "fish":
        return any(_matches_member(item, _FISH) for item in ingredients)
    if category == "seafood":
        return any(
            _matches_member(item, (*_FISH, *_SHELLFISH)) for item in ingredients
        )
    return "vegetarian" in classify_recipe(recipe)


__all__ = [
    "FoodCategory",
    "canonical_food_category",
    "recipe_matches_category",
]
