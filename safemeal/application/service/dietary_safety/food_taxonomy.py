"""Food-category matching used for preference ranking, separate from safety rules."""

from __future__ import annotations

from .ingredient_terms import INGREDIENT_ALIASES
from .recipe_safety import normalize_ingredient_name


def ingredient_belongs_to_category(ingredient: str, category: str) -> bool:
    """Return category membership without broadening allergy matching semantics."""

    normalized = normalize_ingredient_name(ingredient)
    members = INGREDIENT_ALIASES.get(category, [category])
    normalized_members = {normalize_ingredient_name(member) for member in members}
    return any(
        member == normalized or (len(member) >= 2 and member in normalized)
        for member in normalized_members
    )


def recipe_matches_food_category(ingredients: list[str], category: str) -> bool:
    return any(ingredient_belongs_to_category(item, category) for item in ingredients)
