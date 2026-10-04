"""Deterministically reduce menu candidate observations into quota progress."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from safemeal.application.contracts.agent.decisions import Observation, ToolCall
from safemeal.application.contracts.agent.menu_planning import (
    MenuExecutionPlan,
    MenuTaskProgress,
    SelectedMenuRecipe,
)
from safemeal.application.contracts.workflow.request_frame import MenuCategory
from safemeal.shared.types import JsonObject, to_json_object


MAX_MENU_CATEGORY_ATTEMPTS = 2


def _normalized_name(value: object) -> str:
    """Return the stable cross-source identity used for menu de-duplication."""

    return str(value or "").strip().casefold()


def update_menu_task_progress(
    *,
    plan_payload: JsonObject,
    progress_payload: JsonObject,
    calls: Sequence[ToolCall],
    observations: Sequence[Observation],
) -> MenuTaskProgress:
    """Assign safe eligible candidates to one quota each and recompute coverage."""

    plan = MenuExecutionPlan.model_validate(plan_payload)
    progress = MenuTaskProgress.model_validate(progress_payload)
    calls_by_id = {call.id: call for call in calls}
    selected = list(progress.selected_recipes)
    # A database recipe has an integer id while the same bundled recipe does not.
    # Name-based identity prevents the two sources from filling two menu slots with
    # what is actually the same dish.
    selected_ids = {
        item.recipe_id for item in selected if item.recipe_id is not None
    }
    selected_names = {_normalized_name(item.name) for item in selected}
    pool = list(progress.candidate_pool)
    attempts = dict(progress.attempted_categories)
    exhausted = set(progress.exhausted_categories)

    for observation in observations:
        call = calls_by_id.get(observation.call_id)
        if call is None or call.tool_name != "search_recipes":
            continue
        raw_category = call.arguments.get("category")
        if raw_category not in plan.required:
            continue
        category: MenuCategory = raw_category  # type: ignore[assignment]
        attempts[category] = attempts.get(category, 0) + 1
        data = observation.data if isinstance(observation.data, Mapping) else {}
        candidates = [
            item
            for item in data.get("items", []) or []
            if isinstance(item, Mapping)
        ]
        added = 0
        current_count = sum(
            category in (item.credited_categories or (item.assigned_category,))
            for item in selected
        )
        needed = max(0, plan.required[category] - current_count)
        for candidate in candidates:
            candidate_json = to_json_object(candidate)
            if candidate_json not in pool:
                pool.append(candidate_json)
            categories = tuple(candidate.get("categories") or ())
            if (
                category not in categories
                or candidate.get("safety_status") not in {None, "eligible"}
                or not candidate.get("name")
            ):
                continue
            candidate_id = candidate.get("id")
            candidate_name = _normalized_name(candidate.get("name"))
            if plan.distinct_recipes and (
                (candidate_id is not None and candidate_id in selected_ids)
                or candidate_name in selected_names
            ):
                continue
            selected.append(
                SelectedMenuRecipe(
                    recipe_id=(
                        int(candidate["id"]) if candidate.get("id") is not None else None
                    ),
                    name=str(candidate["name"]),
                    assigned_category=category,
                    categories=categories,
                    credited_categories=(
                        tuple(
                            candidate_category
                            for candidate_category in categories
                            if candidate_category in plan.required
                            and sum(
                                candidate_category
                                in (
                                    item.credited_categories
                                    or (item.assigned_category,)
                                )
                                for item in selected
                            )
                            < plan.required[candidate_category]
                        )
                        if plan.allow_cross_category_counting
                        else (category,)
                    ),
                    main_ingredients=tuple(candidate.get("main_ingredients") or ()),
                    evidence_call_id=observation.call_id,
                )
            )
            if candidate_id is not None:
                selected_ids.add(candidate_id)
            selected_names.add(candidate_name)
            added += 1
            if added >= needed:
                break
        fulfilled_count = sum(
            category in (item.credited_categories or (item.assigned_category,))
            for item in selected
        )
        if (
            fulfilled_count < plan.required[category]
            and attempts[category] >= MAX_MENU_CATEGORY_ATTEMPTS
        ):
            exhausted.add(category)

    fulfilled = {
        category: sum(
            category in (item.credited_categories or (item.assigned_category,))
            for item in selected
        )
        for category in plan.required
    }
    remaining = {
        category: max(0, required - fulfilled[category])
        for category, required in plan.required.items()
    }
    complete = all(value == 0 for value in remaining.values())
    blocked = [
        category
        for category, count in remaining.items()
        if count > 0 and category in exhausted
    ]
    coverage_history = (
        *progress.coverage_history,
        {
            "batch": len(progress.coverage_history) + 1,
            "fulfilled": fulfilled,
            "remaining": remaining,
        },
    )
    return MenuTaskProgress(
        fulfilled=fulfilled,
        remaining=remaining,
        selected_recipes=tuple(selected),
        candidate_pool=tuple(pool),
        attempted_categories=attempts,
        exhausted_categories=tuple(
            category for category in plan.required if category in exhausted
        ),
        coverage_history=coverage_history,
        complete=complete,
        partial_reason=(
            "以下分类在现有来源中候选不足：" + "、".join(blocked)
            if blocked and all(
                count == 0 or category in exhausted
                for category, count in remaining.items()
            )
            else ""
        ),
    )


__all__ = ["MAX_MENU_CATEGORY_ATTEMPTS", "update_menu_task_progress"]
