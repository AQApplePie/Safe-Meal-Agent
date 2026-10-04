"""Normalize negative food mentions before they become executable constraints."""

from __future__ import annotations

import re

from safemeal.application.contracts.dietary_safety.requirements import (
    DietaryPreference,
)
from safemeal.application.contracts.workflow.request_frame import (
    CurrentConstraint,
    RequestFrame,
    RequestTarget,
    RequestTask,
)
from safemeal.application.service.recipes.food_category import canonical_food_category


_NEGATIVE_PATTERN = re.compile(
    r"(?P<cue>不喜欢|不爱吃|讨厌|不太想吃|不想吃|不能吃|不要|不吃|别)"
    r"(?P<value>[^，。；;,.！？!?]{1,20})"
)
_STRONG_CUES = {"不想吃", "不能吃", "不要", "不吃", "别"}


def _terms(value: str) -> tuple[str, ...]:
    """Extract compact coordinated mentions, not complete request phrases."""

    value = re.split(r"推荐|安排|帮|给|做|来|有没有", value)[0]
    values = []
    for item in re.split(r"(?:也)?(?:不要|不吃|别)|[、和及与\s]+", value):
        term = item.strip("的菜食物料理东西一点一些")
        if term:
            values.append(term)
    return tuple(dict.fromkeys(values))


def normalize_negation_scope(message: str, frame: RequestFrame) -> RequestFrame:
    """Make negated mentions exclusive from positive target/include semantics."""

    negative: list[tuple[str, bool]] = []
    for match in _NEGATIVE_PATTERN.finditer(message):
        strong = match.group("cue") in _STRONG_CUES
        negative.extend((term, strong) for term in _terms(match.group("value")))
    if not negative:
        return frame

    negative_values = {value for value, _ in negative}
    preferences = [
        item
        for item in frame.turn_preferences
        if not (
            item.kind == "include_ingredient" and item.value in negative_values
        )
    ]
    constraints = list(frame.current_constraints)
    for value, strong in negative:
        category = canonical_food_category(value)
        if category is not None:
            constraints = [
                item
                for item in constraints
                if not (item.kind == "food_category" and item.value == category)
            ]
            if strong and not any(
                item.kind == "avoid_food_category" and item.value == category
                for item in constraints
            ):
                constraints.append(
                    CurrentConstraint(kind="avoid_food_category", value=category)
                )
        normalized_value = "辣椒" if value in {"辣", "辣味"} else value
        preference = DietaryPreference(
            kind=("taste" if value in {"辣", "辣味"} else "avoid_ingredient"),
            value=("不辣" if value in {"辣", "辣味"} else value),
            required=strong,
            source="input",
        )
        if preference not in preferences:
            preferences.append(preference)
        if strong and category is None and not any(
            item.kind == "restriction" and item.value == normalized_value
            for item in constraints
        ):
            constraints.append(
                CurrentConstraint(kind="restriction", value=normalized_value)
            )

    target = frame.target
    if target.ingredient in negative_values or (
        target.recipe_name
        and any(value in target.recipe_name for value in negative_values)
        and frame.primary_task == "recipe_detail"
    ):
        target = RequestTarget()
    tasks = frame.tasks
    requested_fields = frame.requested_fields
    exact_match_required = frame.exact_match_required
    if frame.primary_task in {"recipe_detail", "out_of_scope"} or not tasks:
        tasks = (RequestTask(kind="recipe_recommendation"),)
        requested_fields = ()
        exact_match_required = False
        target = RequestTarget()
    return frame.model_copy(
        update={
            "tasks": tasks,
            "current_constraints": tuple(dict.fromkeys(constraints)),
            "turn_preferences": tuple(preferences),
            "target": target,
            "requested_fields": requested_fields,
            "exact_match_required": exact_match_required,
        }
    )


__all__ = ["normalize_negation_scope"]
