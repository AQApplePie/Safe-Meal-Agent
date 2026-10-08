"""服务于 Planner 节点的计划约束。

本模块在模型给出语义计划后，补齐检索、菜谱生成和饮食安全调用，并执行重复调用
及预算限制；它不调用模型或执行工具。
"""

from __future__ import annotations
from safemeal.agent.contracts.decisions import ModelBudgetUsage

from uuid import uuid4

from safemeal.agent.runtime.orchestration.action_policy import validate_tool_actions
from safemeal.agent.contracts.decisions import PlanDecision, ToolCall
from safemeal.agent.runtime.aggregation.retrieval_routing import (
    is_pure_knowledge_request,
    knowledge_retrieval_tools,
)
from safemeal.agent.contracts.state import AgentState, AgentStateUpdate
from safemeal.agent.runtime.tools.contracts.base import ToolSpecification


def _retrieval_call(tool_name: str, question: str) -> ToolCall:
    return ToolCall(
        id=f"kb-route-{tool_name}-{uuid4().hex[:10]}",
        tool_name=tool_name,
        arguments={"query": question},
        purpose=(
            "检索与用户问题直接相关的原文证据。"
            if tool_name == "search_knowledge"
            else "检索跨文档关系并归纳主题证据。"
        ),
        success_criteria="返回可追踪、可用于回答当前问题的知识库证据。",
    )


def _apply_retrieval_guards(
    calls: list[ToolCall], question: str, tool_specs: list[ToolSpecification]
) -> list[ToolCall]:
    available = {spec.name for spec in tool_specs}
    guarded_tools = tuple(
        tool_name
        for tool_name in knowledge_retrieval_tools(question)
        if tool_name in available
    )
    if not guarded_tools:
        return calls
    guarded_calls = [
        _retrieval_call(tool_name, question) for tool_name in guarded_tools
    ]
    if is_pure_knowledge_request(question):
        return guarded_calls
    existing = {call.tool_name for call in calls}
    return [
        *calls,
        *(call for call in guarded_calls if call.tool_name not in existing),
    ][:4]


def _apply_generation_guard(
    calls: list[ToolCall],
    *,
    question: str,
    available_tools: set[str],
    intent: str | None,
) -> tuple[list[ToolCall], bool]:
    requested = intent == "generate" or any(
        call.tool_name == "generate_recipe" for call in calls
    )
    if not requested:
        return calls, False
    if "generate_recipe" in available_tools and not any(
        call.tool_name == "generate_recipe" for call in calls
    ):
        return [
            ToolCall(
                id=f"recipe-generation-{uuid4().hex[:12]}",
                tool_name="generate_recipe",
                arguments={"requirements": question},
                purpose="生成满足用户要求且通过 Schema 与确定性规则校验的新菜谱。",
                success_criteria="返回完整食材数量、连续步骤、营养和约束校验结果。",
            )
        ], True
    return calls, True


def _apply_safety_guard(
    calls: list[ToolCall],
    *,
    state: AgentState,
    dietary_active: bool,
    generation_requested: bool,
    available_tools: set[str],
) -> tuple[list[ToolCall], bool]:
    already_queried = any(
        item.tool_name
        in {
            "recommend_recipes",
            "dietary_safe_recipe_query",
            "dietary_safety_filter",
        }
        for item in state.get("observations", [])
    )
    has_safety_call = any(
        call.tool_name in {"recommend_recipes", "dietary_safe_recipe_query"}
        for call in calls
    )
    needs_guard = (
        dietary_active
        and not generation_requested
        and not is_pure_knowledge_request(state["question"])
        and not already_queried
        and not has_safety_call
    )
    if not needs_guard:
        return calls, False
    if "recommend_recipes" not in available_tools:
        return calls, True
    safety_call = ToolCall(
        id=f"dietary-safety-{uuid4().hex[:12]}",
        tool_name="recommend_recipes",
        arguments={"limit": 3},
        purpose="确定性验证候选菜是否满足本轮忌口或过敏约束。",
        success_criteria="只把 safe_recipes 作为推荐；excluded/unknown 不得推荐。",
    )
    return [safety_call, *calls[:3]], False


def build_planning_update(
    *,
    state: AgentState,
    decision: PlanDecision,
    tool_specs: list[ToolSpecification],
    budget: ModelBudgetUsage,
) -> AgentStateUpdate:
    """执行确定性的检索路由、安全调用、生成调用和预算限制。"""

    calls = list(decision.calls if decision.decision == "tools" else [])
    question = state["question"]
    calls = _apply_retrieval_guards(calls, question, tool_specs)
    dietary = state.get("dietary_constraints") or {}
    dietary_active = bool(isinstance(dietary, dict) and dietary.get("active"))
    available_tools = {spec.name for spec in tool_specs}
    calls, generation_requested = _apply_generation_guard(
        calls,
        question=question,
        available_tools=available_tools,
        intent=state.get("agent_context", {}).get("intent"),
    )
    calls, safety_gate_blocked = _apply_safety_guard(
        calls,
        state=state,
        dietary_active=dietary_active,
        generation_requested=generation_requested,
        available_tools=available_tools,
    )
    action_policy = validate_tool_actions(
        state=state,
        calls=calls,
        tool_specs=tool_specs,
        model_budget=budget,
    )
    calls = action_policy.calls
    return {
        "pending_calls": calls,
        "planning_rationale": decision.rationale,
        "direct_answer": (
            decision.direct_answer or ""
            if not dietary_active and not generation_requested
            else ""
        ),
        "evidence_sufficient": (
            decision.decision == "answer"
            and not dietary_active
            and not generation_requested
        ),
        "missing_information": [],
        "route": (
            "tools"
            if calls
            else "safety-blocked"
            if safety_gate_blocked
            else "direct-answer"
        ),
        "safety_gate_blocked": safety_gate_blocked,
        "budget_exhausted": action_policy.budget_exhausted,
        "loop_stop_reason": action_policy.stop_reason,
    }


__all__ = ["ModelBudgetUsage", "build_planning_update"]
