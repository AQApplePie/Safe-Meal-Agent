"""按过敏、忌口和饮食类型过滤结构化菜谱。"""

from __future__ import annotations

from collections.abc import Iterable

from safemeal.modules.dietary.application.recipe_safety import (
    ingredient_matches_forbidden_term,
)
from safemeal.modules.recipe.contracts.models import DietaryType, Recipe


_LAND_MEAT_TERMS = frozenset({"猪肉", "牛肉", "羊肉", "鸡肉", "鸭肉", "火腿", "腊肉"})
_SEAFOOD_TERMS = frozenset({"鱼", "虾", "蟹", "贝", "鱿鱼", "章鱼", "鲍鱼", "海参"})
_ANIMAL_PRODUCT_TERMS = frozenset(
    {"鸡蛋", "鸭蛋", "蛋", "牛奶", "奶油", "黄油", "奶酪", "蜂蜜"}
)


class DietaryRecipeFilter:

    @staticmethod
    def excluded_terms_for(dietary_types: Iterable[DietaryType]) -> tuple[str, ...]:
        forbidden: set[str] = set()
        for dietary_type in dietary_types:
            if dietary_type is DietaryType.VEGETARIAN:
                forbidden.update(_LAND_MEAT_TERMS | _SEAFOOD_TERMS)
            elif dietary_type is DietaryType.VEGAN:
                forbidden.update(
                    _LAND_MEAT_TERMS | _SEAFOOD_TERMS | _ANIMAL_PRODUCT_TERMS
                )
            elif dietary_type is DietaryType.PESCATARIAN:
                forbidden.update(_LAND_MEAT_TERMS)
        return tuple(sorted(forbidden))

    def is_recipe_allowed(
        self,
        recipe: Recipe,
        *,
        excluded_ingredients: Iterable[str] = (),
        dietary_types: Iterable[DietaryType] = (),
    ) -> bool:
        resolved_dietary_types = tuple(dietary_types)
        forbidden = tuple(excluded_ingredients) + self.excluded_terms_for(
            resolved_dietary_types
        )
        if not forbidden:
            return True
        for item in recipe.ingredients:
            category = (item.ingredient.category or "").casefold()
            if resolved_dietary_types and not category:
                return False
            if DietaryType.VEGETARIAN in resolved_dietary_types and category.startswith(
                ("肉类", "水产")
            ):
                return False
            if DietaryType.VEGAN in resolved_dietary_types and category.startswith(
                ("肉类", "水产", "蛋类", "奶类")
            ):
                return False
            if (
                DietaryType.PESCATARIAN in resolved_dietary_types
                and category.startswith("肉类")
            ):
                return False
            if any(
                ingredient_matches_forbidden_term(item.ingredient.name, term)
                for term in forbidden
            ):
                return False
        return True

    def filter_recipes(
        self,
        recipes: Iterable[Recipe],
        *,
        excluded_ingredients: Iterable[str] = (),
        dietary_types: Iterable[DietaryType] = (),
    ) -> tuple[Recipe, ...]:
        seen: set[int] = set()
        allowed: list[Recipe] = []
        for recipe in recipes:
            if recipe.id in seen:
                continue
            seen.add(recipe.id)
            if self.is_recipe_allowed(
                recipe,
                excluded_ingredients=excluded_ingredients,
                dietary_types=dietary_types,
            ):
                allowed.append(recipe)
        return tuple(allowed)


__all__ = ["DietaryRecipeFilter"]
