"""Planner 节点。

根据用户问题、历史上下文、记忆和工具清单决定是否直接回答或调用一组工具。
"""

from uuid import uuid4

from SafeMealAgent.back.application.observability import trace_span
from SafeMealAgent.back.application.domain.recipe_generation import is_recipe_generation_request

from ..decision_engine import DecisionEngine
from ..models import ToolCall
from ..state import AgentState, AgentStateUpdate
from ..tool_registry import ToolRegistry
from ..loop_control import filter_new_tool_calls, model_cost_usage, model_token_usage
from ..routing_policy import is_pure_knowledge_request, knowledge_retrieval_tools


def _retrieval_call(tool_name: str, question: str) -> ToolCall:
    return ToolCall(
        id=f"kb-route-{tool_name}-{uuid4().hex[:10]}",
        tool_name=tool_name,
        arguments={"query": question},
        purpose=(
            "检索与用户问题直接相关的原文证据。"
            if tool_name == "milvus_vector_search"
            else "检索跨文档关系并归纳主题证据。"
        ),
        success_criteria="返回可追踪、可用于回答当前问题的知识库证据。",
    )


def create_planner_node(engine: DecisionEngine, registry: ToolRegistry):
    async def planner(state: AgentState) -> AgentStateUpdate:
        # 节点 Span 记录“Planner 收到了什么、决定了什么”。模型调用本身会在
        # DecisionEngine 中形成更细粒度的 model_call，因此二者不会混为一谈。
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
            calls = list(decision.calls if decision.decision == "tools" else [])
            guarded_retrieval_tools = tuple(
                tool_name
                for tool_name in knowledge_retrieval_tools(state["question"])
                if any(spec.name == tool_name for spec in tool_specs)
            )
            if guarded_retrieval_tools:
                guarded_calls = [
                    _retrieval_call(tool_name, state["question"])
                    for tool_name in guarded_retrieval_tools
                ]
                if is_pure_knowledge_request(state["question"]):
                    # A pure request for documents must not silently become a MySQL
                    # recipe lookup just because the question also contains a dish name.
                    calls = guarded_calls
                else:
                    existing = {call.tool_name for call in calls}
                    calls = [
                        *calls,
                        *(call for call in guarded_calls if call.tool_name not in existing),
                    ][:4]
            dietary = state.get("dietary_constraints") or {}
            dietary_active = bool(isinstance(dietary, dict) and dietary.get("active"))
            dietary_exclusions = list(dietary.get("excluded_ingredients") or [])
            generation_requested = is_recipe_generation_request(state["question"])
            generation_available = any(
                spec.name == "generate_recipe" for spec in tool_specs
            )
            has_generation_call = any(
                call.tool_name == "generate_recipe" for call in calls
            )
            if (
                generation_requested
                and generation_available
                and not has_generation_call
            ):
                calls = [
                    ToolCall(
                        id=f"recipe-generation-{uuid4().hex[:12]}",
                        tool_name="generate_recipe",
                        arguments={
                            "requirements": state["question"],
                            "exclude_ingredients": dietary_exclusions,
                        },
                        purpose="生成满足用户要求且通过 Schema 与确定性规则校验的新菜谱。",
                        success_criteria="返回完整食材数量、连续步骤、营养和约束校验结果。",
                    )
                ]
            elif generation_requested and dietary_active:
                calls = [
                    (
                        call.model_copy(
                            update={
                                "arguments": {
                                    **call.arguments,
                                    "exclude_ingredients": dietary_exclusions,
                                }
                            }
                        )
                        if call.tool_name == "generate_recipe"
                        else call
                    )
                    for call in calls
                ]
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
                call.tool_name
                in {"recommend_recipes", "dietary_safe_recipe_query"}
                for call in calls
            )
            safety_tool_available = any(
                spec.name == "recommend_recipes" for spec in tool_specs
            )
            safety_gate_blocked = False
            if (
                dietary_active
                and not generation_requested
                and not is_pure_knowledge_request(state["question"])
                and not already_queried
                and not has_safety_call
            ):
                if safety_tool_available:
                    safety_call = ToolCall(
                        id=f"dietary-safety-{uuid4().hex[:12]}",
                        tool_name="recommend_recipes",
                        arguments={
                            "exclude_ingredients": list(
                                dietary.get("excluded_ingredients") or []
                            ),
                            "limit": 3,
                        },
                        purpose="确定性验证候选菜是否满足本轮忌口或过敏约束。",
                        success_criteria=(
                            "只把 safe_recipes 作为推荐；excluded/unknown 不得推荐。"
                        ),
                    )
                    calls = [safety_call, *calls[:3]]
                else:
                    safety_gate_blocked = True
            remaining_calls = state.get("max_tool_calls", 12) - state.get(
                "tool_call_count", 0
            )
            calls, duplicate_count = filter_new_tool_calls(
                calls,
                executed_signatures=state.get("executed_call_signatures", []),
                remaining_calls=remaining_calls,
            )
            token_budget_exhausted = model_token_usage() >= state.get(
                "max_model_tokens", 20_000
            )
            current_cost, cost_complete = model_cost_usage()
            max_cost = state.get("max_model_cost", 0.0)
            cost_budget_exhausted = bool(
                max_cost > 0 and cost_complete and current_cost >= max_cost
            )
            cost_usage_unavailable = bool(max_cost > 0 and not cost_complete)
            if (
                token_budget_exhausted
                or cost_budget_exhausted
                or cost_usage_unavailable
            ):
                calls = []
            output: AgentStateUpdate = {
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
                    else "safety-blocked" if safety_gate_blocked else "direct-answer"
                ),
                "safety_gate_blocked": safety_gate_blocked,
                "budget_exhausted": token_budget_exhausted
                or cost_budget_exhausted
                or cost_usage_unavailable
                or remaining_calls <= 0,
                "loop_stop_reason": (
                    "model_token_budget"
                    if token_budget_exhausted
                    else (
                        "model_cost_budget"
                        if cost_budget_exhausted
                        else (
                            "model_cost_unavailable"
                            if cost_usage_unavailable
                            else (
                                "tool_call_budget"
                                if remaining_calls <= 0
                                else (
                                    "duplicate_tool_call"
                                    if duplicate_count and not calls
                                    else ""
                                )
                            )
                        )
                    )
                ),
            }
            span.set_output(output)
            return output

    return planner
