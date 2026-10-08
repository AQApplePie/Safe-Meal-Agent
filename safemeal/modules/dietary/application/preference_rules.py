"""提取非过敏偏好并依据证据判断满足情况。"""

import re
from collections.abc import Mapping
from typing import Any, Literal, cast
from safemeal.modules.dietary.contracts.requirements import (
    DietaryPreference,
    PreferenceAssessment,
)
from safemeal.modules.dietary.contracts.constraints import RecipeSafetyRecord
from safemeal.modules.recipe.contracts.models import DietaryType, Recipe
from safemeal.modules.dietary.application.dietary_filter import DietaryRecipeFilter
from .recipe_safety import ingredient_matches_forbidden_term
from .ingredient_terms import INGREDIENT_ALIASES, SPICY_INGREDIENT_TERMS
from .food_taxonomy import recipe_matches_food_category
from .constraint_evaluator import ConstraintEvaluator
from safemeal.modules.dietary.contracts.control_plane import ToolEvidence
from safemeal.shared.contracts.semantic import ConstraintStatement


def preference_from_memory(
    memory: Mapping[str, Any],
) -> DietaryPreference | None:
    """Translate one typed memory without reparsing its display sentence.

    ``memory_key`` is the machine-readable fact extracted when the memory was
    created.  ``memory_value`` is deliberately ignored here because it is only
    presentation/audit text; parsing it again can turn phrases such as
    ``用户偏好鱼`` into unstable sentence fragments.
    """

    memory_type = str(memory.get("memory_type") or "").strip()
    key = str(memory.get("memory_key") or "").strip()
    if not key:
        return None



    if memory_type == "taste_preference":
        if key in {"清淡", "辣", "不辣"}:
            return DietaryPreference(kind="taste", value=key, source="memory")
        kind = "include_ingredient" if key in INGREDIENT_ALIASES else "other"
        return DietaryPreference(kind=kind, value=key, source="memory")

    if memory_type == "taste_dislike":
        if key == "辣":
            return DietaryPreference(kind="taste", value="不辣", source="memory")
        return DietaryPreference(
            kind="avoid_ingredient", value=key, source="memory"
        )

    # Cooking time is stored as e.g. ``30分钟`` but the requirement contract

    if memory_type == "cooking_time":
        match = re.fullmatch(r"(\d{1,4})\s*分钟", key)
        if match and 1 <= int(match[1]) <= 10080:
            return DietaryPreference(
                kind="max_minutes", value=match[1], source="memory"
            )
        return None

    if memory_type == "cooking_equipment":
        return DietaryPreference(kind="equipment", value=key, source="memory")



    if memory_type in {"health_goal", "cooking_constraint"}:
        return DietaryPreference(kind="other", value=key, source="memory")

    return None


def preferences_from_text(
    text: str, source: Literal["input", "history", "memory", "provided"]
) -> list[DietaryPreference]:
    values: list[DietaryPreference] = []

    def add(kind, value, required=False):
        values.append(
            DietaryPreference(
                kind=kind, value=str(value), required=required, source=source
            )
        )

    def clean_food_term(value: str) -> str:

        term = re.split(
            r"[、和及]|的菜|口味|但是|但|然后|请|帮|给|推荐|有没有|是否",
            value,
        )[0]
        return re.sub(r"^(?:我|本人|一份|一道|几个|几道)", "", term).strip()


    for clause in re.split(r"[，。；;！？!?\n]|但是|但", text):
        if re.search(r"假如|假设|例如|比如|如果", clause):
            continue
        required = bool(re.search(r"必须|只能|一定要|务必", clause))
        if "清淡" in clause and not re.search(r"不(?:要|喜欢|想).*清淡", clause):
            add("taste", "清淡", required)
        if re.search(r"不能吃辣|不吃辣|不要辣|不放辣|不加辣|不辣", clause):
            add(
                "taste",
                "不辣",
                required
                or bool(
                    re.search(r"不能吃辣|不吃辣|不要辣|不放辣|不加辣|不辣", clause)
                ),
            )
        elif re.search(
            r"(?<!不)喜欢.*辣|(?<!不)想吃.*辣|(?<!不)要辣", clause
        ):
            add("taste", "辣", required)
        for match in re.finditer(r"(\d{1,3})\s*分钟(?:内|以内|左右)?", clause):
            if 1 <= int(match[1]) <= 10080:
                add(
                    "max_minutes",
                    match[1],
                    required or bool(re.search(r"分钟(?:内|以内)|不超过|最多", clause)),
                )
        for label, kind in (
            ("纯素", "vegan"),
            ("素食", "vegetarian"),
            ("鱼素", "pescatarian"),
        ):
            if label in clause and not re.search(r"不(?:要|吃|是).*" + label, clause):
                add("dietary_type", kind, required or "只吃" in clause)



        for match in re.finditer(
            r"(?<!不)(?:喜欢|爱吃|偏好)([^，。；;]{1,12})", clause
        ):
            term = clean_food_term(match[1])
            if term and term not in {"辣", "清淡"}:
                add(
                    "include_ingredient" if term in INGREDIENT_ALIASES else "other",
                    term,
                    required,
                )
        if source == "input":
            for match in re.finditer(
                r"(?:想吃|想要吃|要吃|来(?:一|两|三|几|\d+)(?:份|道)?)([\u4e00-\u9fff]{1,12})",
                clause,
            ):
                term = clean_food_term(match[1])
                if term and term not in {"菜", "食谱", "东西", "饭", "晚饭"}:
                    add("include_ingredient", term, True)
        for match in re.finditer(r"(?:不喜欢|不爱吃|讨厌)([^，。；;]{1,12})", clause):
            term = clean_food_term(match[1])
            if term and term not in {"辣", "清淡"}:
                add("avoid_ingredient", term)
            elif term == "辣":
                add("taste", "不辣")

        # “不含 X 的 Y” carries two independent hard requirements: exclude X


        if source == "input":
            for match in re.finditer(
                r"(?:没有|不含|不放|不加)([\u4e00-\u9fff]{1,8})的([\u4e00-\u9fff]{1,12})",
                clause,
            ):
                excluded = clean_food_term(match[1])
                target = clean_food_term(match[2])
                if excluded:
                    add("avoid_ingredient", excluded, True)
                if target and target not in {"菜", "食谱", "食物", "东西"}:
                    add("include_ingredient", target, True)
        for match in re.finditer(
            r"(?:必须包含|必须含|必须有|一定要有|包含|含有|含|用)([\u4e00-\u9fff]{1,8}?)(?:做|制作|设计|生成|的|、|和|$)",
            clause,
        ):
            term = match[1].strip()
            if re.search(r"不(?:包)?$", clause[: match.start()]):
                continue
            if term and term not in {"餐", "户", "资料", "知识库"}:
                add(
                    "include_ingredient",
                    term,
                    required or match[0].startswith(("必须", "一定")),
                )
        for equipment in ("微波炉", "烤箱", "空气炸锅", "电饭煲", "蒸锅", "平底锅"):
            if equipment in clause and re.search(r"只能|只有|必须用", clause):
                add("equipment", equipment, True)
    return values


def assess_preference(
    preference: DietaryPreference, record: RecipeSafetyRecord
) -> PreferenceAssessment:
    rows = record.evidence
    status: Literal["satisfied", "not_satisfied", "unknown"] = "unknown"
    reason = "结构化证据不足，无法确认此要求。"
    kind, value = preference.kind, preference.value
    if kind in {"avoid_ingredient", "include_ingredient"}:
        found = (
            recipe_matches_food_category(record.ingredients, value)
            if value in INGREDIENT_ALIASES
            else any(
                ingredient_matches_forbidden_term(item, value)
                for item in record.ingredients
            )
        )
        if found or record.safety_status == "safe":
            satisfied = found if kind == "include_ingredient" else not found
            status = "satisfied" if satisfied else "not_satisfied"
            reason = "已对照完整食材证据。"
    elif kind == "max_minutes":
        times = [row.get("total_time_minutes") for row in rows]
        if times and all(
            isinstance(t, (int, float)) and not isinstance(t, bool) and t >= 0
            for t in times
        ):
            status = (
                "satisfied"
                if all(float(cast(float, t)) <= int(value) for t in times)
                else "not_satisfied"
            )
            reason = f"食谱标注耗时与 {value} 分钟上限对照。"
    elif kind == "taste":
        tastes = [row.get("taste") for row in rows]
        spicy = any(
            ingredient_matches_forbidden_term(i, term)
            for i in record.ingredients
            for term in SPICY_INGREDIENT_TERMS
        )
        if value == "不辣":
            decision = ConstraintEvaluator().evaluate(
                ConstraintStatement(
                    type="taste",
                    value="non_spicy",
                    strength=(
                        "strong_requirement"
                        if preference.required
                        else "soft_preference"
                    ),
                ),
                ToolEvidence(
                    recipe_name=record.name,
                    ingredients=tuple(record.ingredients),
                    ingredients_complete=record.safety_status != "unknown",
                    source_complete=record.safety_status != "unknown",
                ),
            )
            status = {
                "satisfied": "satisfied",
                "violated": "not_satisfied",
                "unknown": "unknown",
            }[decision.status]
            reason = decision.reason
        elif value == "清淡" and spicy:
            status, reason = "not_satisfied", "食材包含辣味配料。"
        elif tastes and all(isinstance(t, str) and t for t in tastes):
            if all(t == value for t in tastes):
                status, reason = "satisfied", "食谱明确标注了相应口味。"
            elif any(t in {"辣", "麻辣", "香辣"} for t in tastes) and value in {
                "不辣",
                "清淡",
            }:
                status, reason = "not_satisfied", "标注口味与偏好冲突。"
        # No salt/oil evidence means '清淡' cannot be inferred from a dish name.
    elif kind == "equipment":
        equipment = [row.get("equipment") for row in rows]
        if equipment and all(
            isinstance(items, list) and items and all(isinstance(i, str) for i in items)
            for items in equipment
        ):
            status = (
                "satisfied"
                if all(set(cast(list[str], items)) <= {value} for items in equipment)
                else "not_satisfied"
            )
            reason = "已对照食谱明确列出的设备。"
    elif kind == "dietary_type":
        forbidden = DietaryRecipeFilter.excluded_terms_for([DietaryType(value)])
        if any(
            ingredient_matches_forbidden_term(i, term)
            for i in record.ingredients
            for term in forbidden
        ):
            status, reason = "not_satisfied", "食材违反所要求的饮食类型。"
        else:
            verified: list[bool | None] = []
            for row in rows:
                try:
                    recipe = Recipe.model_validate(row)
                    verified.append(
                        DietaryRecipeFilter().is_recipe_allowed(
                            recipe, dietary_types=[DietaryType(value)]
                        )
                    )
                except ValueError:
                    verified.append(None)
            if verified and all(item is True for item in verified):
                status, reason = "satisfied", "完整食材及类别通过饮食类型检查。"
            elif any(item is False for item in verified):

                reason = "食材类别不完整或不符合饮食类型，无法确认满足要求。"
    return PreferenceAssessment(preference=preference, status=status, reason=reason)
