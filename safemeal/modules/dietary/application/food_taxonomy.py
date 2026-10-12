"""提供与过敏规则隔离的食物分类匹配。"""

from __future__ import annotations

from .ingredient_terms import INGREDIENT_ALIASES
from .recipe_safety import normalize_ingredient_name


# 方法说明：ingredient_belongs_to_category
# 作用：判断食材是否属于目标食物分类。
# 入参：
#   ingredient（str）：当前食材条目。
#   category（str）：目标食材或菜品分类。
# 出参：bool；目标食材或菜谱是否满足当前分类或禁止词匹配规则。
def ingredient_belongs_to_category(ingredient: str, category: str) -> bool:

    normalized = normalize_ingredient_name(ingredient)
    members = INGREDIENT_ALIASES.get(category, [category])
    normalized_members = {normalize_ingredient_name(member) for member in members}
    return any(
        member == normalized or (len(member) >= 2 and member in normalized)
        for member in normalized_members
    )


# 方法说明：recipe_matches_food_category
# 作用：判断菜谱是否满足请求中的菜品分类要求。
# 入参：
#   ingredients（list[str]）：菜谱使用的完整食材集合。
#   category（str）：目标食材或菜品分类。
# 出参：bool；目标食材或菜谱是否满足当前分类或禁止词匹配规则。
def recipe_matches_food_category(ingredients: list[str], category: str) -> bool:
    return any(ingredient_belongs_to_category(item, category) for item in ingredients)
