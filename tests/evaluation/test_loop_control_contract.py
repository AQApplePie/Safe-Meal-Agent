"""Regression checks for repeated Tool outcome convergence."""

from safemeal.application.agent.orchestration.loop_control import (
    filter_new_tool_calls,
)
from safemeal.application.contracts.agent.decisions import ToolCall


def _call(call_id: str = "next") -> ToolCall:
    return ToolCall(
        id=call_id,
        tool_name="search_recipes",
        arguments={"name_contains": "未知菜", "exact_name": True, "limit": 1},
        purpose="lookup",
        success_criteria="found or explicit not found",
    )


def test_one_failed_outcome_allows_one_bounded_retry():
    call = _call()
    accepted, duplicates = filter_new_tool_calls(
        [call],
        executed_signatures=[],
        remaining_calls=5,
        tool_trace=[
            {"tool": call.tool_name, "args": call.arguments, "status": "NOT_FOUND"}
        ],
    )

    assert accepted == [call]
    assert duplicates == 0


def test_same_tool_args_and_outcome_twice_stops_third_call():
    call = _call()
    repeated = {
        "tool": call.tool_name,
        "args": call.arguments,
        "status": "NOT_FOUND",
    }

    accepted, duplicates = filter_new_tool_calls(
        [call],
        executed_signatures=[],
        remaining_calls=5,
        tool_trace=[repeated, repeated],
    )

    assert accepted == []
    assert duplicates == 1


def test_changed_query_is_not_blocked_by_previous_outcome():
    previous = _call("old")
    rewritten = previous.model_copy(
        update={"id": "new", "arguments": {"name_contains": "另一道菜", "limit": 1}}
    )
    trace = {
        "tool": previous.tool_name,
        "args": previous.arguments,
        "status": "NOT_FOUND",
    }

    accepted, duplicates = filter_new_tool_calls(
        [rewritten],
        executed_signatures=[],
        remaining_calls=5,
        tool_trace=[trace, trace],
    )

    assert accepted == [rewritten]
    assert duplicates == 0
