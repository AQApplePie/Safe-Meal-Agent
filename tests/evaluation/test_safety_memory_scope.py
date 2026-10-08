"""Regression contracts for current safety and persistent memory scope."""

from safemeal.agent.runtime.tools.policy import review_tool_calls
from safemeal.agent.contracts.decisions import ToolCall
from safemeal.agent.understanding.request_understanding import (
    RequestUnderstandingService,
)


def test_allergy_turn_keeps_business_task_memory_update_and_current_constraint():
    frame = RequestUnderstandingService().understand(
        "我对花生过敏，有没有什么没有花生的菜？"
    )

    assert frame.primary_task == "recipe_recommendation"
    assert ("allergy", "花生") in [
        (item.kind, item.value) for item in frame.memory_updates
    ]
    assert ("allergy", "花生") in [
        (item.kind, item.value) for item in frame.current_constraints
    ]


def test_current_allergy_is_injected_before_tool_execution():
    call = ToolCall(
        id="recommend",
        tool_name="recommend_recipes",
        arguments={"requested_count": 4, "candidate_limit": 12, "limit": 12},
        purpose="recommend",
        success_criteria="four safe recipes",
    )

    accepted, rejected = review_tool_calls(
        [call], {"active": True, "excluded_ingredients": ["花生"]}
    )

    assert not rejected
    assert accepted[0].arguments["exclude_ingredients"] == ["花生"]


def test_temporary_dislike_is_current_scope_not_persistent_memory():
    frame = RequestUnderstandingService().understand("今天不想吃鱼")

    assert not frame.memory_updates
    assert ("avoid_food_category", "fish") in [
        (item.kind, item.value) for item in frame.current_constraints
    ]


def test_explicit_future_allergy_is_current_and_persistent():
    frame = RequestUnderstandingService().understand(
        "以后都不要给我推荐花生，我过敏"
    )

    assert ("allergy", "花生") in [
        (item.kind, item.value) for item in frame.memory_updates
    ]
    assert ("allergy", "花生") in [
        (item.kind, item.value) for item in frame.current_constraints
    ]
