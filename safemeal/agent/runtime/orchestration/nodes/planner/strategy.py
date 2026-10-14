"""Planner 使用的确定性下一步行动策略。"""

from __future__ import annotations

from dataclasses import dataclass

from safemeal.agent.contracts.context import AgentContext
from safemeal.agent.contracts.decisions import ToolCall
from safemeal.agent.contracts.intent import IntentDecision
from safemeal.agent.contracts.state import AgentState

from .menu_planning import build_menu_search_plan


# 类说明（数据契约类）：DeterministicAction
# 作用：无需模型推理即可确定的单步行动。
@dataclass(frozen=True)
class DeterministicAction:
    """无需模型推理即可确定的单步行动。"""

    # 字段说明：calls
    # 作用：待执行或待审核的工具调用列表。
    # 类型：list[ToolCall]。
    calls: list[ToolCall]
    # 字段说明：route
    # 作用：HTTP 路由模板或业务路由标识。
    # 类型：str。
    route: str
    # 字段说明：rationale
    # 作用：规划或审核给出的理由说明。
    # 类型：str。
    rationale: str
    # 字段说明：direct_answer
    # 作用：无需继续调用工具即可返回给用户的答复文本。
    # 类型：str。
    # 初始值：''。
    direct_answer: str = ""


# 方法说明：_counted_recommendation_action
# 作用：为显式数量要求生成推荐工具调用及对应数量参数。
# 入参：
#   intent（IntentDecision）：已识别的本轮请求意图。
#   context（AgentContext）：本轮执行上下文。
#   available_tools（set[str]）：本轮可用工具集合。
# 出参：DeterministicAction | None；规则选定的工具动作或None（未取得结果）。
def _counted_recommendation_action(
    intent: IntentDecision,
    context: AgentContext,
    available_tools: set[str],
) -> DeterministicAction | None:
    frame = context.request_frame
    if (
        intent.kind != "recommend"
        or frame is None
        or "recommend_recipes" not in available_tools
        or not (
            frame.recommendation_count is not None
            or any(
                item.kind in {"food_category", "avoid_food_category"}
                for item in frame.current_constraints
            )
        )
    ):
        return None

    requested_count = frame.recommendation_count or 3
    food_categories = [
        item.value for item in frame.current_constraints if item.kind == "food_category"
    ]
    excluded_categories = [
        item.value
        for item in frame.current_constraints
        if item.kind == "avoid_food_category"
    ]
    return DeterministicAction(
        calls=[
            ToolCall(
                id=f"recommend-count-{requested_count}",
                tool_name="recommend_recipes",
                arguments={
                    "requested_count": requested_count,
                    "food_categories": food_categories,
                    "exclude_food_categories": excluded_categories,
                },
                purpose="按 RequestFrame 中的显式数量召回并筛选推荐菜品。",
                success_criteria=(
                    f"返回 {requested_count} 道通过约束且互不重复的菜品，"
                    "不足时返回结构化 PARTIAL。"
                ),
            )
        ],
        route="tools",
        rationale="显式数量由 RequestFrame 确定性传递到推荐工具。",
    )


# 方法说明：_exact_recipe_action
# 作用：将明确菜名或标识转换为确定性的菜谱详情调用。
# 入参：
#   context（AgentContext）：本轮执行上下文。
#   state（AgentState）：Agent 完整图状态。
#   available_tools（set[str]）：本轮可用工具集合。
# 出参：DeterministicAction | None；规则选定的工具动作或None（未取得结果）。
def _exact_recipe_action(
    context: AgentContext,
    state: AgentState,
    available_tools: set[str],
) -> DeterministicAction | None:
    frame = context.request_frame
    if (
        frame is None
        or not frame.exact_match_required
        or not frame.target.recipe_name
        or not frame.requested_fields
        or "search_recipes" not in available_tools
        or any(
            item.tool_name == "search_recipes"
            and isinstance(item.data, dict)
            and item.data.get("exact_name") is True
            for item in state.get("observations", [])
        )
    ):
        return None
    return DeterministicAction(
        calls=[
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
        route="tools",
        rationale="明确菜名使用 search_recipes 确定性多源查询。",
    )


# 方法说明：choose_deterministic_action
# 作用：按优先级选择一个确定性下一步行动，不执行预算或工具调用。
# 入参：
#   intent（IntentDecision）：已识别的本轮请求意图。
#   context（AgentContext）：本轮执行上下文。
#   state（AgentState）：Agent 完整图状态。
#   available_tools（set[str]）：本轮可用工具集合。
# 出参：DeterministicAction | None；规则选定的工具动作或None（未取得结果）。
def choose_deterministic_action(
    *,
    intent: IntentDecision,
    context: AgentContext,
    state: AgentState,
    available_tools: set[str],
) -> DeterministicAction | None:
    """按优先级选择一个确定性下一步行动，不执行预算或工具调用。"""

    counted = _counted_recommendation_action(intent, context, available_tools)
    if counted is not None:
        return counted
    if intent.kind == "menu_planning":
        return DeterministicAction(
            calls=build_menu_search_plan(
                state.get("menu_execution_plan", {}),
                state.get("menu_task_progress", {}),
            ),
            route="tools",
            rationale="根据尚未满足的菜单分类配额，按缺口批量搜索候选。",
        )
    exact = _exact_recipe_action(context, state, available_tools)
    if exact is not None:
        return exact
    if intent.kind in {"memory", "clarify", "out_of_scope"}:
        return DeterministicAction(
            calls=[],
            route=intent.kind,
            rationale="该意图无需工具证据即可结束本轮。",
            direct_answer=intent.clarification
            or (
                "已识别本轮饮食偏好。"
                if intent.kind == "memory"
                else "我可以帮助你查询、推荐和生成食谱，或解答烹饪与食材问题。"
            ),
        )
    return None


__all__ = ["DeterministicAction", "choose_deterministic_action"]
