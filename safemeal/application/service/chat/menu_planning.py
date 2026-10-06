"""从单轮请求中确定性提取复杂菜单的显式分类配额。

请求理解模型负责一般语义；“三道凉菜”等明确数字由代码提取，避免配额计算依赖
模型对“十几道”等模糊数量的猜测。
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
_REPLACEMENT_PATTERN = re.compile(
    r"重新|重选|重来|替换|换(?:一|两|三|四|五|六|七|八|九|十|\d|个|道|份|掉|成)?|改成|调整为"
)
_ORDINAL_MENU_REFERENCE_PATTERN = re.compile(
    r"第([一二两三四五六七八九十]|\d{1,2})(?:个|道|份)?\s*"
    r"(凉菜|冷菜|热菜|素菜|荤菜|汤品|主食|凉|热|素|荤|汤)"
)


def extract_menu_modification(
    message: str,
) -> tuple[MenuCategory | None, int | None]:
    """提取需要替换的菜单分类及可选的新配额。"""

    if not _REPLACEMENT_PATTERN.search(message):
        return None, None
    # 目标分类必须来自包含替换动作的分句，避免“素菜保留”干扰“荤菜重新推荐”。
    clauses = re.split(r"[，,。；;]", message)
    replacement_clause = next(
        (clause for clause in clauses if _REPLACEMENT_PATTERN.search(clause)), message
    )
    category = next(
        (
            _CATEGORY_ALIASES[label]
            for label in sorted(_CATEGORY_ALIASES, key=len, reverse=True)
            if label in replacement_clause
        ),
        None,
    )
    if category is None:
        # “荤菜不要鸡肉，重新推荐”省略了动作后的分类，应继承最近出现的分类。
        mentioned = [
            (message.rfind(label), _CATEGORY_ALIASES[label])
            for label in sorted(_CATEGORY_ALIASES, key=len, reverse=True)
            if label in message
        ]
        category = max(mentioned, default=(-1, None), key=lambda item: item[0])[1]
    count = None
    for number, label in _QUOTA_PATTERN.findall(message):
        if _CATEGORY_ALIASES[label] == category:
            count = _number(number)
            break
    if count is None and category is not None:
        changed_count = re.search(
            r"(?:改成|换成|调整为)\s*([一二两三四五六七八九十]|\d{1,2})\s*(?:道|份|个)?",
            message,
        )
        if changed_count:
            count = _number(changed_count.group(1))
    if (
        count is None
        and category is not None
        and re.search(r"换一个|换一道|另一个", message)
    ):
        count = 1
    return category, count


def resolve_active_menu_recipe_reference(
    message: str, active_menu: dict[str, object]
) -> str | None:
    """根据持久化活动菜单解析分类内部的顺序引用。"""

    match = _ORDINAL_MENU_REFERENCE_PATTERN.search(message)
    if match is None:
        return None
    ordinal = _number(match.group(1))
    category = _CATEGORY_ALIASES[match.group(2)]
    progress = active_menu.get("progress")
    if not isinstance(progress, dict):
        return None
    selected = progress.get("selected_recipes")
    if not isinstance(selected, list):
        return None
    category_recipes = [
        item
        for item in selected
        if isinstance(item, dict) and item.get("assigned_category") == category
    ]
    if ordinal < 1 or ordinal > len(category_recipes):
        return None
    name = category_recipes[ordinal - 1].get("name")
    return name if isinstance(name, str) and name else None


def _number(value: str) -> int:
    return _NUMBER_VALUES.get(value, int(value) if value.isdigit() else 0)


def extract_menu_planning_requirements(
    message: str,
) -> tuple[str | None, MenuPlanningRequirements | None]:
    """存在至少两个显式分类配额时返回复杂菜单规划要求。"""

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
    # 无显式分类数量的配餐请求属于自适应推荐，以 None 表示没有配额契约。
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
    """判断用户是否要求安排一餐，允许没有显式分类配额。"""

    return bool(re.search(r"安排|菜单|配餐|宴席|家宴|聚餐", message))


__all__ = [
    "extract_menu_modification",
    "extract_menu_planning_requirements",
    "is_menu_planning_request",
    "resolve_active_menu_recipe_reference",
]
