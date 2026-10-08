"""按本轮请求字段渲染精确菜谱证据。"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any


_NUTRITION_LABELS = {
    "calories": "热量",
    "protein_g": "蛋白质",
    "carbs_g": "碳水化合物",
    "fat_g": "脂肪",
}


def _ingredient_lines(recipe: Mapping[str, Any]) -> list[str]:

    return [
        f"- {item.get('name')}：{item.get('amount') or '适量'}"
        for item in recipe.get("ingredients", []) or []
        if isinstance(item, Mapping) and item.get("name")
    ]


def _step_lines(recipe: Mapping[str, Any]) -> list[str]:

    raw = str(recipe.get("steps") or "").strip()
    if not raw:
        return []
    rows = [item.strip(" -\t") for item in raw.splitlines() if item.strip(" -\t")]
    if len(rows) == 1:
        rows = [
            item.strip()
            for item in re.split(r"(?<=[。！？!?])\s*", rows[0])
            if item.strip()
        ]
    return [
        row if re.match(r"^\d+[.、．)]", row) else f"{index}. {row}"
        for index, row in enumerate(rows, start=1)
    ]


def _nutrition_lines(recipe: Mapping[str, Any]) -> list[str]:

    nutrition = recipe.get("nutrition")
    if not isinstance(nutrition, Mapping):
        return []
    units = {"calories": "kcal", "protein_g": "g", "carbs_g": "g", "fat_g": "g"}
    lines = [
        f"- {_NUTRITION_LABELS[key]}：{nutrition[key]}{units[key]}"
        for key in _NUTRITION_LABELS
        if nutrition.get(key) is not None
    ]
    basis = nutrition.get("basis")
    if lines and basis:
        lines.append(f"- 计算基准：{'整份' if basis == 'per_recipe' else '每100克'}")
    return lines


def render_exact_recipe_detail(
    recipe: Mapping[str, Any], requested_fields: Iterable[str]
) -> str:

    name = str(recipe.get("name") or "该食谱")
    fields = tuple(dict.fromkeys(requested_fields)) or ("ingredients", "steps")
    sections: list[str] = []
    for field in fields:
        if field == "ingredients":
            lines = _ingredient_lines(recipe)
            sections.append(
                f"{name}的材料：\n" + "\n".join(lines)
                if lines
                else f"{name}：当前来源没有提供可提取的材料列表。"
            )
        elif field == "steps":
            lines = _step_lines(recipe)
            sections.append(
                f"{name}的做法：\n" + "\n".join(lines)
                if lines
                else f"{name}：当前来源没有提供具体做法。"
            )
        elif field == "nutrition":
            lines = _nutrition_lines(recipe)
            sections.append(
                f"{name}的营养信息：\n" + "\n".join(lines)
                if lines
                else f"{name}：当前来源没有提供结构化营养信息。"
            )
        elif field == "time":
            minutes = recipe.get("total_time_minutes")
            sections.append(
                f"{name}预计需要 {minutes} 分钟。"
                if isinstance(minutes, (int, float)) and not isinstance(minutes, bool)
                else f"{name}：当前来源没有提供制作时间。"
            )
    return "\n\n".join(sections)


__all__ = ["render_exact_recipe_detail"]
