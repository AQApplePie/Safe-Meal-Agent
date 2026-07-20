"""Recipe-to-document formatting for knowledge ingestion."""

from typing import List

from SafeMealAgent.back.shared.types import JsonObject


def format_recipe_document(recipe: JsonObject) -> str:
    """Convert structured recipe fields into an embedding-friendly document."""

    parts: List[str] = []
    field_labels = (
        ("name", "菜名"),
        ("category", "分类"),
        ("difficulty", "难度"),
    )
    for field, label in field_labels:
        if value := recipe.get(field):
            parts.append(f"{label}：{value}")

    if time_cost := recipe.get("time") or recipe.get("cook_time"):
        parts.append(f"耗时：{time_cost}")

    ingredients = recipe.get("ingredients") or recipe.get("ingredient_list")
    if ingredients:
        formatted = (
            "、".join(str(item) for item in ingredients)
            if isinstance(ingredients, list)
            else str(ingredients)
        )
        parts.append(f"食材：{formatted}")

    steps = recipe.get("steps")
    if isinstance(steps, list):
        parts.extend(f"步骤{index + 1}：{step}" for index, step in enumerate(steps))
    elif steps:
        parts.append(f"步骤：{steps}")

    if tips := recipe.get("tips"):
        parts.append(f"小贴士：{tips}")

    nutrition = recipe.get("nutrition")
    if isinstance(nutrition, dict):
        parts.append(
            "营养：" + "、".join(f"{key}: {value}" for key, value in nutrition.items())
        )
    elif nutrition:
        parts.append(f"营养：{nutrition}")

    return "\n".join(parts)
