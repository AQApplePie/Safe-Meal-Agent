"""最终回答节点。

Responder 只依据 Observation 中的证据组织答案，不直接访问数据库或外部检索服务。
"""

from langchain_core.messages import AIMessage

from safemeal.agent.workflow.streaming import emit_answer_chunk
from safemeal.agent.safety.answer import (
    dietary_constraint_is_active,
    render_dietary_safety_answer,
)
from .sources import collect_answer_sources
from .recipe_detail import render_exact_recipe_detail
from .recommendation import render_recipe_recommendations

from safemeal.agent.runtime.model import AgentModelGateway
from .retrieval_routing import is_pure_knowledge_request
from safemeal.modules.conversation.contracts.conversation.models import RouterInfo
from safemeal.agent.contracts.state import AgentState, AgentStateUpdate
from safemeal.agent.runtime.menu_output import render_menu_plan


def create_responder_node(model_gateway: AgentModelGateway):
    async def respond(state: AgentState) -> AgentStateUpdate:
        observations = state.get("observations", [])
        intent = state.get("intent")
        context = state.get("agent_context") or {}
        frame = context.get("request_frame") if isinstance(context, dict) else None
        exact = next(
            (
                item
                for item in observations
                if item.tool_name == "search_recipes"
                and isinstance(item.data, dict)
                and item.data.get("exact_name") is True
            ),
            None,
        )
        if exact is not None and exact.data.get("status") == "ERROR":
            answer = "食谱数据源暂时无法完成查询，本轮未继续重复检索。"
            await emit_answer_chunk(answer)
        elif exact is not None and exact.data.get("status") == "NOT_FOUND":
            query = exact.data.get("query") or "该食谱"
            answer = f"未在可用食谱来源中找到“{query}”，因此不能用其他菜替代回答。"
            await emit_answer_chunk(answer)
        elif exact is not None and exact.data.get("status") in {"FOUND", "FIELD_MISSING"}:
            recipe = (exact.data.get("items") or [{}])[0]
            requested_fields = (
                frame.get("requested_fields", []) if isinstance(frame, dict) else []
            )
            answer = render_exact_recipe_detail(recipe, requested_fields)
            if exact.data.get("status") == "FIELD_MISSING":
                missing = "、".join(exact.data.get("missing_fields") or [])
                answer += f"\n\n该食谱已找到，但来源缺少字段：{missing}。"
            source_url = recipe.get("source_url")
            source_title = recipe.get("source_title")
            if source_url:
                answer += f"\n\n来源：{source_title or source_url}（{source_url}）"
            if recipe.get("ingredients_complete") is False:
                answer += "\n\n安全提示：该来源没有提供可确认完整的配料表，无法据此确认全部过敏风险。"
            await emit_answer_chunk(answer)
        elif intent is not None and intent.kind in {
            "memory",
            "clarify",
            "out_of_scope",
        }:
            answer = state["direct_answer"]
            await emit_answer_chunk(answer)
        elif intent is not None and intent.kind == "menu_planning":


            answer = render_menu_plan(
                state.get("menu_execution_plan") or {},
                state.get("menu_task_progress") or {},
            )
            await emit_answer_chunk(answer)
        elif dietary_constraint_is_active(
            state.get("dietary_constraints")
        ) and not is_pure_knowledge_request(state["question"]):
            answer = render_dietary_safety_answer(observations)
            await emit_answer_chunk(answer)
        elif intent is not None and intent.kind == "recommend":
            recommendation_count = (
                frame.get("recommendation_count") if isinstance(frame, dict) else None
            )
            answer = render_recipe_recommendations(
                observations,
                limit=recommendation_count or 3,
            )
            if answer is None:
                answer = await model_gateway.answer(
                    question=state["question"],
                    conversation_history=state.get("conversation_history", []),
                    observations=observations,
                    reflection_rationale=state.get("reflection_rationale", ""),
                    evidence_sufficient=state.get("evidence_sufficient", False),
                    missing_information=state.get("missing_information", []),
                )
            else:
                await emit_answer_chunk(answer)
        elif state.get("direct_answer") and not observations:
            answer = state["direct_answer"]
            await emit_answer_chunk(answer)
        elif state.get("budget_exhausted"):
            usable = [
                item.summary
                for item in observations
                if item.ok and item.has_data and item.summary.strip()
            ][:5]
            answer = (
                "已达到本轮执行预算。当前可确认的证据摘要：\n- " + "\n- ".join(usable)
                if usable
                else "已达到本轮执行预算，当前没有足够证据生成可靠答案。"
            )
            await emit_answer_chunk(answer)
        else:
            answer = await model_gateway.answer(
                question=state["question"],
                conversation_history=state.get("conversation_history", []),
                observations=observations,
                reflection_rationale=state.get("reflection_rationale", ""),
                evidence_sufficient=state.get("evidence_sufficient", False),
                missing_information=state.get("missing_information", []),
            )
        if state.get("budget_exhausted"):
            reason = state.get("loop_stop_reason") or "agent_budget"
            answer = (
                answer.rstrip()
                + f"\n\n说明：本轮已达到执行预算（{reason}），以上为当前证据范围内的部分结果。"
            )
            await emit_answer_chunk(
                f"\n\n说明：本轮已达到执行预算（{reason}），以上为当前证据范围内的部分结果。"
            )
        counted = next(
            (
                (
                    int(item.data["requested_count"]),
                    int(item.data.get("fulfilled_count") or 0),
                )
                for item in reversed(observations)
                if item.tool_name == "recommend_recipes"
                and item.ok
                and isinstance(item.data, dict)
                and item.data.get("requested_count") is not None
            ),
            None,
        )
        if counted is not None and counted[1] < counted[0]:
            requested, fulfilled = counted
            partial_note = (
                f"\n\n说明：你请求了 {requested} 道，目前可核验的结果只有 "
                f"{fulfilled} 道，因此这是部分结果。"
            )
            answer = answer.rstrip() + partial_note
            await emit_answer_chunk(partial_note)

        route = state.get("route", "finish")
        router = RouterInfo(
            type="agent-tools-loop",
            logic=(
                state.get("reflection_rationale")
                or state.get("planning_rationale")
                or route
            ),
        )
        output: AgentStateUpdate = {
            "messages": [AIMessage(content=answer)],
            "sources": collect_answer_sources(observations),
            "router": router,
        }
        return output

    return respond
