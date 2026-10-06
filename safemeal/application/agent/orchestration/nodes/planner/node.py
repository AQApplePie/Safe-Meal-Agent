"""Planner 节点入口；模型规划后的确定性约束由同目录模块处理。"""

from .intent import resolve_agent_intent
from safemeal.application.contracts.agent.decisions import ToolCall
from safemeal.application.agent.model import AgentModelGateway, IntentClassifier
from safemeal.application.contracts.agent.context import AgentContext
from safemeal.application.streaming import emit_workflow_progress

from .constraints import (
    ModelBudgetUsage,
    build_planning_update,
)
from .menu_planning import build_menu_search_plan

from safemeal.application.agent.orchestration.loop_control import (
    current_model_cost_usage,
    current_model_token_usage,
    filter_new_tool_calls,
)
from safemeal.application.contracts.agent.state import AgentState, AgentStateUpdate
from safemeal.application.ports.tools.tool_executor import ToolExecutor


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
        frame = context.request_frame
        if (
            intent.kind == "recommend"
            and frame is not None
            and (
                frame.recommendation_count is not None
                or any(
                    item.kind in {"food_category", "avoid_food_category"}
                    for item in frame.current_constraints
                )
            )
            and "recommend_recipes"
            in {spec.name for spec in tool_executor.specifications()}
        ):
            requested_count = frame.recommendation_count or 3
            food_categories = [
                item.value
                for item in frame.current_constraints
                if item.kind == "food_category"
            ]
            exclude_food_categories = [
                item.value
                for item in frame.current_constraints
                if item.kind == "avoid_food_category"
            ]





            candidate_limit = (
                200
                if food_categories or exclude_food_categories
                else min(50, max(requested_count * 3, requested_count + 6))
            )
            return {
                "intent": intent,
                "agent_context": state["agent_context"],
                "observations": observations,
                "pending_calls": [
                    ToolCall(
                        id=f"recommend-count-{requested_count}",
                        tool_name="recommend_recipes",
                        arguments={
                            "requested_count": requested_count,
                            "candidate_limit": candidate_limit,


                            "limit": min(50, candidate_limit),
                            "food_categories": food_categories,
                            "exclude_food_categories": exclude_food_categories,
                        },
                        purpose="按 RequestFrame 中的显式数量召回并筛选推荐菜品。",
                        success_criteria=(
                            f"返回 {requested_count} 道通过约束且互不重复的菜品，"
                            "不足时返回结构化 PARTIAL。"
                        ),
                    )
                ],
                "planning_rationale": "显式数量由 RequestFrame 确定性传递到推荐工具。",
                "route": "tools",
            }
        if intent.kind == "menu_planning":
            planned_calls = build_menu_search_plan(
                state.get("menu_execution_plan", {}),
                state.get("menu_task_progress", {}),
            )
            remaining_calls = state.get("max_tool_calls", 12) - state.get(
                "tool_call_count", 0
            )
            calls, duplicate_count = filter_new_tool_calls(
                planned_calls,
                executed_signatures=state.get("executed_call_signatures", []),
                remaining_calls=remaining_calls,
                tool_trace=state.get("tool_trace", []),
            )
            budget_exhausted = remaining_calls <= 0
            return {
                "intent": intent,
                "agent_context": state["agent_context"],
                "observations": observations,
                "pending_calls": calls,
                "planning_rationale": (
                    "根据尚未满足的菜单分类配额，按缺口批量搜索候选。"
                ),
                "route": "tools" if calls else "respond",
                "budget_exhausted": budget_exhausted,
                "loop_stop_reason": (
                    "tool_call_budget"
                    if budget_exhausted
                    else "duplicate_tool_call"
                    if duplicate_count and not calls
                    else ""
                ),
            }
        if (
            frame is not None
            and frame.exact_match_required
            and frame.target.recipe_name
            and frame.requested_fields
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
                            "required_fields": list(frame.requested_fields),
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
