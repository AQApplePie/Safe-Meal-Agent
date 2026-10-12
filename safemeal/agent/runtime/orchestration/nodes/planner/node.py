"""Planner 节点入口；模型规划后的确定性约束由同目录模块处理。"""

from .intent import resolve_agent_intent
from safemeal.agent.runtime.model import AgentModelGateway, IntentClassifier
from safemeal.agent.contracts.context import AgentContext
from safemeal.agent.workflow.streaming import emit_workflow_progress

from .constraints import (
    build_planning_update,
)
from safemeal.agent.runtime.orchestration.loop_control import (
    current_model_cost_usage,
    current_model_token_usage,
)
from safemeal.agent.runtime.orchestration.action_policy import validate_tool_actions
from safemeal.agent.contracts.state import AgentState, AgentStateUpdate
from safemeal.agent.contracts.decisions import ModelBudgetUsage
from safemeal.agent.runtime.tools.ports.tool_executor import ToolExecutor
from .strategy import choose_deterministic_action


# 方法说明：create_planner_node
# 作用：构造决定下一步工具动作或直接回答的规划节点。
# 入参：
#   model_gateway（AgentModelGateway）：语言模型调用能力。
#   tool_executor（ToolExecutor）：已装配的工具注册与执行组件。
# 出参：按实现返回；绑定当前依赖的图节点函数，接收图状态并返回局部状态更新。
def create_planner_node(
    model_gateway: AgentModelGateway,
    tool_executor: ToolExecutor,
):
    # 方法说明：planner
    # 作用：结合意图、约束和工具证据生成下一步调用计划。
    # 入参：
    #   state（AgentState）：Agent 完整图状态。
    # 出参：AgentStateUpdate；Agent 图节点局部状态更新。
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
        decision = None
        if deterministic is None:
            decision = await model_gateway.plan(
                question=state["question"],
                conversation_history=state.get("conversation_history", []),
                tool_specs=tool_specs,
                observations=observations,
            )
        current_cost, cost_complete = current_model_cost_usage()
        budget = ModelBudgetUsage(
            tokens=current_model_token_usage(),
            cost=current_cost,
            cost_complete=cost_complete,
        )
        if deterministic is not None:
            action_policy = validate_tool_actions(
                state=state,
                calls=deterministic.calls,
                tool_specs=tool_specs,
                model_budget=budget,
            )
            output: AgentStateUpdate = {
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
        else:
            assert decision is not None
            output = build_planning_update(
                state=state,
                decision=decision,
                tool_specs=tool_specs,
                budget=budget,
            )
        output["intent"] = intent
        output["agent_context"] = state["agent_context"]
        output["observations"] = observations
        return output

    return planner
