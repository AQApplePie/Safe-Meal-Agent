"""Planner 节点入口；模型规划后的确定性约束由同目录模块处理。"""

from .intent import resolve_agent_intent
from safemeal.application.contracts.agent.decisions import ToolCall
from safemeal.application.ports.llm.intent_classifier import IntentClassifier
from safemeal.application.contracts.agent.context import AgentContext
from safemeal.application.streaming import emit_workflow_progress

from .constraints import (
    ModelBudgetUsage,
    build_planning_update,
)

from safemeal.application.ports.llm.language_model_gateway import LanguageModelGateway
from safemeal.application.agent.utils.loop_control import (
    current_model_cost_usage,
    current_model_token_usage,
)
from safemeal.application.contracts.agent.state import AgentState, AgentStateUpdate
from safemeal.application.ports.tools.tool_executor import ToolExecutor


def create_planner_node(
    model_gateway: LanguageModelGateway,
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
        frame = context.request_frame
        if (
            frame is not None
            and frame.understanding_status == "accepted"
            and frame.exact_match_required
            and frame.target.recipe_name
            and not any(
                item.tool_name == "search_recipes"
                and isinstance(item.data, dict)
                and item.data.get("exact_name") is True
                for item in state.get("observations", [])
            )
            and "search_recipes"
            in {spec.name for spec in tool_executor.specifications()}
        ):
            return {
                "intent": intent,
                "agent_context": state["agent_context"],
                "observations": observations,
                "pending_calls": [
                    ToolCall(
                        id="exact-recipe-search",
                        tool_name="search_recipes",
                        arguments={
                            "name_contains": frame.target.recipe_name,
                            "exact_name": True,
                            "limit": 1,
                        },
                        purpose="查询用户明确指定的食谱",
                        success_criteria="按数据源优先级返回该菜或明确NOT_FOUND/ERROR",
                    )
                ],
                "planning_rationale": "明确菜名使用search_recipes确定性多源查询。",
                "route": "tools",
            }
        if intent.kind in {"memory", "clarify", "out_of_scope"}:
            return {
                "intent": intent,
                "agent_context": state["agent_context"],
                "observations": observations,
                "pending_calls": [],
                "route": intent.kind,
                "direct_answer": intent.clarification
                or (
                    "已识别本轮饮食偏好。"
                    if intent.kind == "memory"
                    else "我可以帮助你查询、推荐和生成食谱，或解答烹饪与食材问题。"
                ),
            }
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
        output["intent"] = intent
        output["agent_context"] = state["agent_context"]
        output["observations"] = observations
        return output

    return planner
