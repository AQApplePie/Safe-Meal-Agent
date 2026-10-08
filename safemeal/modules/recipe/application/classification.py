"""从可信字段派生菜谱的多维分类。"""

from __future__ import annotations

from collections.abc import Iterable

from safemeal.modules.recipe.contracts.models import Recipe
from safemeal.shared.contracts.request_frame import MenuCategory


_COLD_MARKERS = ("凉拌", "冷盘", "冷菜", "沙拉", "拍黄瓜", "凉菜")
_SOUP_MARKERS = ("汤", "羹")
_STAPLE_MARKERS = ("饭", "面", "馒头", "包子", "饺", "馄饨", "饼", "粥", "粉", "花卷", "窝头")
_ANIMAL_CATEGORY_PREFIXES = ("肉类", "水产", "蛋类")
_ANIMAL_NAME_MARKERS = (
    "肉", "鸡", "鸭", "鹅", "鱼", "虾", "蟹", "牛", "羊", "猪", "排骨", "蛋", "火腿", "腊肠",
)


def classify_menu_categories(
    *,
    name: str,
    ingredient_names: Iterable[str],
    ingredient_categories: Iterable[str] = (),
    description: str = "",
) -> tuple[MenuCategory, ...]:

    text = f"{name} {description}"
    ingredients = tuple(str(item) for item in ingredient_names)
    categories = tuple(str(item) for item in ingredient_categories)
    result: list[MenuCategory] = []
    is_cold = any(marker in text for marker in _COLD_MARKERS)
    is_soup = any(marker in name for marker in _SOUP_MARKERS)
    is_staple = any(marker in name for marker in _STAPLE_MARKERS)
    has_animal = any(
        category.startswith(_ANIMAL_CATEGORY_PREFIXES) for category in categories
    ) or any(
        marker in ingredient for ingredient in ingredients for marker in _ANIMAL_NAME_MARKERS
    )
    if is_cold:
        result.append("cold_dish")
    elif not is_staple:
        result.append("hot_dish")
    if has_animal:
        result.append("meat")
    elif ingredients:
        result.append("vegetarian")
    if is_soup:
        result.append("soup")
    if is_staple:
        result.append("staple")
    return tuple(dict.fromkeys(result))


def classify_recipe(recipe: Recipe) -> tuple[MenuCategory, ...]:
    return classify_menu_categories(
        name=recipe.name,
        description=recipe.description or "",
        ingredient_names=(item.ingredient.name for item in recipe.ingredients),
        ingredient_categories=(
            item.ingredient.category or "" for item in recipe.ingredients
        ),
    )


__all__ = ["classify_menu_categories", "classify_recipe"]
