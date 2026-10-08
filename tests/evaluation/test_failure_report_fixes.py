"""Regression tests derived directly from the exploratory failure report."""

from __future__ import annotations

import pytest

from safemeal.agent.runtime.orchestration.nodes.planner.intent import (
    intent_from_request_frame,
)
from safemeal.agent.contracts.context import AgentContext
from safemeal.shared.contracts.request_frame import RequestFrame
from safemeal.shared.contracts.request_frame import (
    CurrentConstraint,
    RequestTarget,
    RequestTask,
)
from safemeal.modules.dietary.contracts.requirements import (
    DietaryPreference,
)
from safemeal.agent.understanding.request_understanding import (
    RequestUnderstandingService,
)
from safemeal.agent.understanding.frame_semantics import (
    RequestFrameSemanticValidator,
)


@pytest.mark.parametrize(
    ("query", "servings", "meal_type"),
    [
        ("给四个人安排午餐", 4, "lunch"),
        ("我媳妇不吃辣，帮我们两个人安排晚饭", 2, "dinner"),
        ("我儿子不喜欢姜，给一家三口安排午饭", 3, "lunch"),
        ("我自己想吃鱼，给我们四个人安排午饭", 4, "lunch"),
    ],
)
def test_adaptive_meal_request_has_no_empty_quota_contract(
    query: str, servings: int | None, meal_type: str
):
    frame = RequestUnderstandingService().understand(query)

    assert frame.primary_task == "menu_planning"
    assert frame.menu_planning is None
    assert frame.servings == servings
    assert frame.meal_type == meal_type
    decision = intent_from_request_frame(AgentContext(request_frame=frame))
    assert decision is not None
    assert decision.kind == "recommend"
    assert decision.reason == "adaptive_meal_request"


def test_explicit_quota_menu_remains_deterministic():
    frame = RequestUnderstandingService().understand("给四个人安排两荤两素一汤")

    assert frame.primary_task == "menu_planning"
    assert frame.servings == 4
    assert frame.menu_planning is not None
    assert {
        item.category: item.count for item in frame.menu_planning.category_quotas
    } == {"meat": 2, "vegetarian": 2, "soup": 1}
    decision = intent_from_request_frame(AgentContext(request_frame=frame))
    assert decision is not None
    assert decision.kind == "menu_planning"


def test_incomplete_request_frame_can_record_validation_errors():
    frame = RequestFrame(
        understanding_status="incomplete",
        validation_errors=("ValidationError",),
    )

    assert frame.validation_errors == ("ValidationError",)


def test_soft_negative_ingredient_never_becomes_positive_include():
    frame = RequestUnderstandingService().understand("我不喜欢姜，推荐几道菜")

    assert not any(
        item.kind == "include_ingredient" and item.value == "姜"
        for item in frame.turn_preferences
    )
    assert any(
        item.kind == "avoid_ingredient"
        and item.value == "姜"
        and item.required is False
        for item in frame.turn_preferences
    )


def test_strong_negative_only_request_is_not_recipe_detail():
    frame = RequestUnderstandingService().understand("不要辣，也不要花椒")

    assert frame.primary_task == "recipe_recommendation"
    assert frame.target.recipe_name is None
    assert not frame.requested_fields
    assert any(
        item.kind == "restriction" and item.value == "辣椒"
        for item in frame.current_constraints
    )
    assert any(
        item.kind == "restriction" and item.value == "花椒"
        for item in frame.current_constraints
    )


def test_temporary_negative_category_does_not_also_include_category():
    frame = RequestUnderstandingService().understand("今天不想吃鱼")

    assert not any(
        item.kind == "food_category" and item.value == "fish"
        for item in frame.current_constraints
    )
    assert any(
        item.kind == "avoid_food_category" and item.value == "fish"
        for item in frame.current_constraints
    )


def test_allergy_remains_hard_safety_after_negation_normalization():
    frame = RequestUnderstandingService().understand("我对花生过敏，推荐四道菜")

    assert any(
        item.kind == "allergy" and item.value == "花生"
        for item in frame.current_constraints
    )


def test_category_does_not_also_become_literal_ingredient():
    malformed = RequestFrame(
        tasks=(RequestTask(kind="recipe_recommendation"),),
        current_constraints=(CurrentConstraint(kind="food_category", value="seafood"),),
        turn_preferences=(
            DietaryPreference(
                kind="include_ingredient",
                value="海鲜",
                required=True,
                source="input",
            ),
        ),
        target=RequestTarget(ingredient="海鲜"),
        recommendation_count=4,
    )

    frame = RequestFrameSemanticValidator().normalize(malformed)

    assert frame.target.ingredient is None
    assert not frame.turn_preferences


@pytest.mark.parametrize(
    ("query", "target", "fields"),
    [
        ("水煮鱼有什么材料？", "水煮鱼", ("ingredients",)),
        ("水煮鱼怎么做？", "水煮鱼", ("steps",)),
        ("水煮鱼要多久？", "水煮鱼", ("time",)),
        ("告诉我水煮鱼的材料和步骤", "水煮鱼", ("ingredients", "steps")),
    ],
)
def test_recipe_detail_semantics_are_complete(query, target, fields):
    frame = RequestUnderstandingService().understand(query)

    assert frame.primary_task == "recipe_detail"
    assert frame.target.recipe_name == target
    assert frame.requested_fields == fields
    assert frame.exact_match_required is True


def test_malformed_recipe_detail_becomes_controlled_clarification():
    malformed = RequestFrame(tasks=(RequestTask(kind="recipe_detail"),))

    frame = RequestFrameSemanticValidator().normalize(malformed)

    assert frame.primary_task == "clarify"
    assert frame.understanding_status == "incomplete"
    assert set(frame.validation_errors) == {
        "recipe_detail_target_missing",
        "recipe_detail_fields_missing",
    }


def test_complete_fallback_detail_contract_remains_executable():
    frame = RequestFrame(
        tasks=(RequestTask(kind="recipe_detail"),),
        target=RequestTarget(recipe_name="水煮鱼"),
        requested_fields=("time",),
        exact_match_required=True,
        understanding_status="fallback",
        fallback_used=True,
    )

    decision = intent_from_request_frame(AgentContext(request_frame=frame))

    assert decision is not None
    assert decision.kind == "recipe_detail"
