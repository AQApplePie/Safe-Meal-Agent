"""Deterministically extract explicit composite menu quotas from one request.

The request-understanding model still owns general semantics. Explicit numbers
such as “三道凉菜” are parsed here because quota arithmetic must not depend on an
LLM guessing how many dishes “十几道” means.
"""

from __future__ import annotations

import re

from safemeal.application.contracts.workflow.request_frame import (
    CategoryQuota,
    MenuCategory,
    MenuPlanningRequirements,
)


_CATEGORY_ALIASES: dict[str, MenuCategory] = {
    "凉菜": "cold_dish",
    "冷菜": "cold_dish",
    "热菜": "hot_dish",
    "素菜": "vegetarian",
    "荤菜": "meat",
    "汤": "soup",
    "汤品": "soup",
    "主食": "staple",
    "凉": "cold_dish",
    "热": "hot_dish",
    "素": "vegetarian",
    "荤": "meat",
}
_NUMBER_VALUES = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
_QUOTA_PATTERN = re.compile(
    r"([一二两三四五六七八九十]|\d{1,2})\s*(?:道|份|个)?\s*"
    r"(凉菜|冷菜|热菜|素菜|荤菜|汤品|主食|凉|热|素|荤|汤)"
)


def _number(value: str) -> int:
    return _NUMBER_VALUES.get(value, int(value) if value.isdigit() else 0)


def extract_menu_planning_requirements(
    message: str,
) -> tuple[str | None, MenuPlanningRequirements | None]:
    """Return a composite plan only when at least two category quotas are explicit."""

    quotas: dict[MenuCategory, int] = {}
    for number, label in _QUOTA_PATTERN.findall(message):
        count = _number(number)
        if count > 0:
            quotas[_CATEGORY_ALIASES[label]] = count
    coordinated = is_menu_planning_request(message)
    if len(quotas) < 2 and not coordinated:
        return None, None

    scenario = None
    for marker in ("农村宴席", "婚宴", "宴席", "聚餐", "家宴"):
        if marker in message:
            scenario = marker
            break
    # A coordinated meal request without explicit category quantities is valid,
    # but it is adaptive rather than quota-driven.  Absence of requirements is
    # deliberately represented as None; an empty value object remains invalid.
    if not quotas:
        return scenario, None
    requirements = MenuPlanningRequirements(
        category_quotas=tuple(
            CategoryQuota(category=category, count=count)
            for category, count in quotas.items()
        ),
        distinct_recipes=True,
        allow_cross_category_counting=False,
    )
    return scenario, requirements


def is_menu_planning_request(message: str) -> bool:
    """Whether the user asks to coordinate a meal, with or without quotas."""

    return bool(re.search(r"安排|菜单|配餐|宴席|家宴|聚餐", message))


__all__ = ["extract_menu_planning_requirements", "is_menu_planning_request"]
