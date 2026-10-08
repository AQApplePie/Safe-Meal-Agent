"""Execution limits remain effective without a monitoring subsystem."""

import asyncio
from types import SimpleNamespace

import pytest

from safemeal.agent.runtime.budget import (
    charge_model_usage,
    current_model_cost_usage,
    current_model_token_usage,
    parse_model_pricing,
    use_model_budget,
)
from safemeal.agent.runtime.orchestration.nodes.planner.constraints import build_planning_update
from safemeal.agent.contracts.decisions import (
    ModelBudgetUsage,
    PlanDecision,
    ToolCall,
)
from safemeal.agent.runtime.tools.contracts.base import ToolSpecification


@pytest.mark.asyncio
async def test_concurrent_runs_have_isolated_budgets_and_child_tasks_share_usage():
    async def run(tokens):
        with use_model_budget({}):

            async def invoke():
                charge_model_usage(
                    "model",
                    SimpleNamespace(
                        usage_metadata={"input_tokens": tokens, "output_tokens": 2}
                    ),
                )

            await asyncio.gather(invoke(), invoke())
            await asyncio.sleep(0)
            return current_model_token_usage()

    assert await asyncio.gather(run(10), run(100)) == [24, 204]
    assert current_model_token_usage() == 0


def test_cost_budget_counts_cached_tokens_and_rejects_unknown_usage():
    prices = parse_model_pricing(
        '{"model":{"input_cost_per_million":2,"output_cost_per_million":4,"cached_input_cost_per_million":1}}'
    )
    with use_model_budget(prices):
        charge_model_usage(
            "model",
            SimpleNamespace(
                usage_metadata={
                    "input_tokens": 100,
                    "output_tokens": 10,
                    "input_token_details": {"cache_read": 20},
                }
            ),
        )
        cost, complete = current_model_cost_usage()
        assert complete and cost == pytest.approx(0.00022)
        charge_model_usage("model", None)
        assert not current_model_cost_usage()[1]
    assert current_model_cost_usage() == (0.0, False)


def test_token_budget_prevents_pending_tool_execution():
    with use_model_budget({}):
        charge_model_usage(
            "model", SimpleNamespace(usage_metadata={"total_tokens": 100})
        )
        cost, complete = current_model_cost_usage()
        update = build_planning_update(
            state={"question": "推荐晚餐", "max_model_tokens": 100},
            decision=PlanDecision(
                decision="tools",
                rationale="search",
                calls=[
                    ToolCall(
                        id="one",
                        tool_name="recommend_recipes",
                        arguments={},
                        purpose="find dinner",
                        success_criteria="recipe found",
                    )
                ],
            ),
            tool_specs=[
                ToolSpecification(
                    name="recommend_recipes",
                    description="recommend",
                    arguments_schema={},
                )
            ],
            budget=ModelBudgetUsage(
                tokens=current_model_token_usage(), cost=cost, cost_complete=complete
            ),
        )
        assert update["pending_calls"] == []
        assert update["budget_exhausted"]
        assert update["loop_stop_reason"] == "model_token_budget"
