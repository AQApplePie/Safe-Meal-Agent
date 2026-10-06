"""根据结构化候选确定性渲染推荐回答。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from safemeal.application.contracts.agent.decisions import Observation


def _ingredient_names(recipe: Mapping[str, Any]) -> list[str]:

    names: list[str] = []
    for item in recipe.get("ingredients", []) or []:
        name: object | None = None
        if isinstance(item, Mapping):
            nested = item.get("ingredient")
            if isinstance(nested, Mapping):
                name = nested.get("name")
            name = name or item.get("name") or item.get("ingredient_name")
        elif isinstance(item, str):
            name = item


        if name and not isinstance(name, bool):
            text = str(name).strip()
            if text and text not in names:
                names.append(text)
    return names


def render_recipe_recommendations(
    observations: Sequence[Observation], *, limit: int = 3
) -> str | None:

    for observation in reversed(observations):
        if observation.tool_name not in {"recommend_recipes", "search_recipes"}:
            continue
        data = observation.data
        if not observation.ok or not isinstance(data, Mapping):
            continue
        if data.get("exact_name") is True:
            continue
        items = [item for item in data.get("items", []) or [] if isinstance(item, Mapping)]
        if not items:
            continue
        selected = items[: max(1, min(limit, 10))]
        lines = [f"可以优先考虑下面这 {len(selected)} 道菜："]
        for recipe in selected:
            name = str(recipe.get("name") or "未命名菜品")
            ingredients = _ingredient_names(recipe)
            detail = f"主要食材有{'、'.join(ingredients)}。" if ingredients else ""
            lines.append(f"- 「{name}」：{detail}".rstrip("："))
        return "\n".join(lines)
    return None


__all__ = ["render_recipe_recommendations"]
