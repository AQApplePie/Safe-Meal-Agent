"""Planner 节点入口；模型规划后的确定性约束由同目录模块处理。"""

from safemeal.application.observability import trace_span
from .constraints import (
    ModelBudgetUsage,
    build_planning_update,
)

from safemeal.application.ports.llm.language_model_gateway import LanguageModelGateway
from safemeal.application.agent.utils.loop_control import current_model_cost_usage, current_model_token_usage
from safemeal.application.agent.utils.state import AgentState, AgentStateUpdate
from safemeal.application.ports.tools.tool_executor import ToolExecutor


def create_planner_node(
    model_gateway: LanguageModelGateway,
    tool_executor: ToolExecutor,
):
    async def planner(state: AgentState) -> AgentStateUpdate:
        with trace_span(
            "agent_node",
            "planner",
            {
                "question": state["question"],
                "observation_count": len(state.get("observations", [])),
            },
        ) as span:
            tool_specs = tool_executor.specifications()
            decision = await model_gateway.plan(
                question=state["question"],
                conversation_history=state.get("conversation_history", []),
                tool_specs=tool_specs,
                observations=state.get("observations", []),
            )
            current_cost, cost_complete = current_model_cost_usage()
            output = build_planning_update(
                state=state,
                decision=decision,
                tool_specs=tool_specs,
                budget=ModelBudgetUsage(
                    tokens=current_model_token_usage(),
                    cost=current_cost,
                    cost_complete=cost_complete,
                ),
            )
            span.set_output(output)
            return output

    return planner
