"""验证 Outer Understanding、Initializer 与统一行动策略的职责边界。"""

import pytest

from safemeal.agent.contracts.context import AgentContext
from safemeal.modules.dietary.contracts.requirements import DietaryRequirements
from safemeal.agent.contracts.decisions import ModelBudgetUsage, ToolCall
from safemeal.agent.runtime.orchestration.action_policy import validate_tool_actions
from safemeal.agent.runtime.orchestration.loop_control import tool_call_signature
from safemeal.agent.runtime.orchestration.nodes.initializer.node import (
    create_initializer_node,
)
from safemeal.agent.runtime.tools.contracts.base import ToolSpecification


def _call(call_id: str, tool_name: str = "search_recipes") -> ToolCall:
    return ToolCall(
        id=call_id,
        tool_name=tool_name,
        arguments={"query": "鱼"},
        purpose="测试统一行动校验",
        success_criteria="行动被正确接受或拒绝",
    )


def _spec(name: str = "search_recipes") -> ToolSpecification:
    return ToolSpecification(name=name, description="测试工具", arguments_schema={})


@pytest.mark.asyncio
async def test_initializer_does_not_mine_constraints_from_raw_history():
    initializer = create_initializer_node(
        max_iterations=4,
        max_tool_calls=12,
        max_model_tokens=20_000,
        max_model_cost=0.0,
    )
    output = await initializer(
        {
            "messages": [
                {"role": "user", "content": "我对花生过敏"},
                {"role": "user", "content": "推荐晚饭"},
            ],
            "agent_context": AgentContext(
                requirements=DietaryRequirements()
            ).model_dump(mode="json"),
        }
    )

    requirements = output["agent_context"]["requirements"]
    assert requirements["allergies"]["active"] is False
    assert output["dietary_constraints"]["active"] is False


def test_action_policy_rejects_unknown_and_duplicate_calls_in_one_place():
    known = _call("known")
    unknown = _call("unknown", "unknown_tool")
    decision = validate_tool_actions(
        state={"executed_call_signatures": [tool_call_signature(known)]},
        calls=[known, unknown],
        tool_specs=[_spec()],
    )

    assert decision.calls == []
    assert decision.duplicate_count == 1
    assert decision.invalid_count == 1
    assert decision.stop_reason == "invalid_tool_action"


def test_action_policy_applies_tool_and_model_budgets_consistently():
    decision = validate_tool_actions(
        state={
            "max_tool_calls": 4,
            "tool_call_count": 1,
            "max_model_tokens": 100,
        },
        calls=[_call("one")],
        tool_specs=[_spec()],
        model_budget=ModelBudgetUsage(tokens=100, cost=0.0, cost_complete=True),
    )

    assert decision.calls == []
    assert decision.budget_exhausted is True
    assert decision.stop_reason == "model_token_budget"


def test_action_policy_rejects_same_signature_twice_in_one_batch():
    decision = validate_tool_actions(
        state={},
        calls=[_call("one"), _call("two")],
        tool_specs=[_spec()],
    )

    assert [call.id for call in decision.calls] == ["one"]
    assert decision.duplicate_count == 1


@pytest.mark.asyncio
async def test_initializer_rejects_unresolved_constraints_instead_of_assuming_safe():
    initializer = create_initializer_node(
        max_iterations=4, max_tool_calls=12, max_model_tokens=20_000, max_model_cost=0.0
    )
    with pytest.raises(ValueError, match="requires resolved dietary requirements"):
        await initializer(
            {
                "messages": [{"role": "user", "content": "花生过敏，推荐晚餐"}],
                "agent_context": {},
            }
        )
