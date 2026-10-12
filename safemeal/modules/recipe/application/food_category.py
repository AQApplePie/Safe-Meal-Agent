"""根据结构化食材判定菜品分类。"""

from __future__ import annotations

from collections.abc import Iterable
from safemeal.modules.recipe.contracts.catalog import FoodCategory

from safemeal.modules.recipe.contracts.models import Recipe
from safemeal.modules.recipe.application.classification import classify_recipe


_FISH = {
    "鱼",
    "鲈鱼",
    "海鲈",
    "黄鱼",
    "大黄鱼",
    "龙利鱼",
    "三文鱼",
    "鳕鱼",
    "鲤鱼",
    "草鱼",
    "鲫鱼",
    "银鱼",
    "带鱼",
    "鱼丸",
    "鱼柳",
}
_SHELLFISH = {
    "虾",
    "虾仁",
    "大虾",
    "海虾",
    "基围虾",
    "虾米",
    "蟹",
    "螃蟹",
    "蟹肉",
    "贝",
    "贝类",
    "扇贝",
    "扇贝肉",
    "蛤",
    "蛤蜊",
    "鱿鱼",
}
_ALIASES: dict[str, FoodCategory] = {
    "鱼": "fish",
    "鱼类": "fish",
    "海鲜": "seafood",
    "水产": "seafood",
    "素菜": "vegetarian",
    "素食": "vegetarian",
}


# 方法说明：canonical_food_category
# 作用：把食材或菜品分类名称映射为内部标准分类。
# 入参：
#   value（str）：当前待转换或校验的值。
# 出参：FoodCategory | None；食材分类或None（未取得结果）。
def canonical_food_category(value: str) -> FoodCategory | None:
    return _ALIASES.get(value.strip())


# 方法说明：_matches_member
# 作用：判断食材名称是否匹配指定食材类别的成员。
# 入参：
#   ingredient（str）：当前食材条目。
#   members（Iterable[str]）：食材类别的成员名称集合。
# 出参：bool；目标食材或菜谱是否满足当前分类或禁止词匹配规则。
def _matches_member(ingredient: str, members: Iterable[str]) -> bool:
    value = ingredient.strip()
    return any(value == member or value.endswith(member) for member in members)


# 方法说明：recipe_matches_category
# 作用：判断菜谱是否满足请求中的菜品分类要求。
# 入参：
#   recipe（Recipe）：当前菜谱或菜谱记录。
#   category（FoodCategory）：目标食材或菜品分类。
# 出参：bool；目标食材或菜谱是否满足当前分类或禁止词匹配规则。
def recipe_matches_category(recipe: Recipe, category: FoodCategory) -> bool:

    ingredients = tuple(item.ingredient.name for item in recipe.ingredients)
    if category == "fish":
        return any(_matches_member(item, _FISH) for item in ingredients)
    if category == "seafood":
        return any(_matches_member(item, (*_FISH, *_SHELLFISH)) for item in ingredients)
    return "vegetarian" in classify_recipe(recipe)


__all__ = [
    "FoodCategory",
    "canonical_food_category",
    "recipe_matches_category",
]
