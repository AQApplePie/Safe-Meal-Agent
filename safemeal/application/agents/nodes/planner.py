"""Thin LangGraph adapter for the planning use case."""

from safemeal.application.observability import trace_span
from safemeal.application.use_cases.agent.planning import (
    ModelBudgetUsage,
    build_planning_update,
)

from ..decision_engine import DecisionEngine
from ..loop_control import model_cost_usage, model_token_usage
from ..state import AgentState, AgentStateUpdate
from ..tool_registry import ToolRegistry


def create_planner_node(engine: DecisionEngine, registry: ToolRegistry):
    async def planner(state: AgentState) -> AgentStateUpdate:
        with trace_span(
            "agent_node",
            "planner",
            {
                "question": state["question"],
                "observation_count": len(state.get("observations", [])),
            },
        ) as span:
            tool_specs = registry.specifications()
            decision = await engine.plan(
                question=state["question"],
                conversation_history=state.get("conversation_history", []),
                tool_specs=tool_specs,
                observations=state.get("observations", []),
            )
            current_cost, cost_complete = model_cost_usage()
            output = build_planning_update(
                state=state,
                decision=decision,
                tool_specs=tool_specs,
                budget=ModelBudgetUsage(
                    tokens=model_token_usage(),
                    cost=current_cost,
                    cost_complete=cost_complete,
                ),
            )
            span.set_output(output)
            return output

    return planner
