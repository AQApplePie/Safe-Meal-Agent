"""Planner 节点入口；模型规划后的确定性约束由同目录模块处理。"""

from .intent import resolve_agent_intent
from safemeal.agent.runtime.model import AgentModelGateway, IntentClassifier
from safemeal.agent.contracts.context import AgentContext
from safemeal.agent.workflow.streaming import emit_workflow_progress

from .constraints import (
    ModelBudgetUsage,
    build_planning_update,
)
from safemeal.agent.runtime.orchestration.loop_control import (
    current_model_cost_usage,
    current_model_token_usage,
)
from safemeal.agent.runtime.orchestration.action_policy import validate_tool_actions
from safemeal.agent.contracts.state import AgentState, AgentStateUpdate
from safemeal.agent.runtime.tools.ports.tool_executor import ToolExecutor
from .strategy import choose_deterministic_action


def create_planner_node(
    model_gateway: AgentModelGateway,
    tool_executor: ToolExecutor,
):
    async def planner(state: AgentState) -> AgentStateUpdate:
        intent = state.get("intent")
        context = AgentContext.model_validate(state.get("agent_context") or {})
        if intent is None:
            await emit_workflow_progress("agent_plan", "正在理解需求并制定计划")
            intent = await resolve_agent_intent(
                state["question"],
                context,
                model_gateway if isinstance(model_gateway, IntentClassifier) else None,
            )
        context.intent = intent.kind
        observations = [
            item.model_copy(deep=True) for item in state.get("observations", [])
        ]
        for item in observations:
            if item.tool_name == "task_context" and isinstance(item.data, dict):
                item.data["intent"] = intent.kind
                item.summary = str(item.data)
        state = {
            **state,
            "intent": intent,
            "agent_context": context.model_dump(mode="json"),
            "observations": observations,
        }
        tool_specs = tool_executor.specifications()
        deterministic = choose_deterministic_action(
            intent=intent,
            context=context,
            state=state,
            available_tools={spec.name for spec in tool_specs},
        )
        if deterministic is not None:
            current_cost, cost_complete = current_model_cost_usage()
            action_policy = validate_tool_actions(
                state=state,
                calls=deterministic.calls,
                tool_specs=tool_specs,
                model_budget=ModelBudgetUsage(
                    tokens=current_model_token_usage(),
                    cost=current_cost,
                    cost_complete=cost_complete,
                ),
            )
            return {
                "intent": intent,
                "agent_context": state["agent_context"],
                "observations": observations,
                "pending_calls": action_policy.calls,
                "route": (
                    "tools"
                    if action_policy.calls
                    else deterministic.route
                    if not deterministic.calls
                    else "respond"
                ),
                "direct_answer": deterministic.direct_answer,
                "planning_rationale": deterministic.rationale,
                "budget_exhausted": action_policy.budget_exhausted,
                "loop_stop_reason": action_policy.stop_reason,
            }
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
        output["intent"] = intent
        output["agent_context"] = state["agent_context"]
        output["observations"] = observations
        return output

    return planner
