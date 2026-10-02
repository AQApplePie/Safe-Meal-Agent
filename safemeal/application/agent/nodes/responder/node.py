"""最终回答节点。

Responder 只依据 Observation 中的证据组织答案，不直接访问数据库或外部检索服务。
"""

from langchain_core.messages import AIMessage

from safemeal.application.streaming import emit_answer_chunk
from safemeal.application.service.dietary_safety.answer import (
    dietary_constraint_is_active,
    render_dietary_safety_answer,
)
from .attribution import collect_answer_sources

from safemeal.application.ports.llm.language_model_gateway import LanguageModelGateway
from safemeal.application.agent.utils.retrieval_routing import is_pure_knowledge_request
from safemeal.application.contracts.conversation.models import RouterInfo
from safemeal.application.contracts.agent.state import AgentState, AgentStateUpdate


def create_responder_node(model_gateway: LanguageModelGateway):
    async def respond(state: AgentState) -> AgentStateUpdate:
        observations = state.get("observations", [])
        intent = state.get("intent")
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
        elif exact is not None and exact.data.get("status") == "FOUND":
            recipe = (exact.data.get("items") or [{}])[0]
            lines = [
                f"- {item.get('name')}：{item.get('amount', '适量')}"
                for item in recipe.get("ingredients", [])
                if isinstance(item, dict) and item.get("name")
            ]
            answer = (
                f"{recipe.get('name')}的材料：\n" + "\n".join(lines)
                if lines
                else f"{recipe.get('name')}：该来源未提供可提取的结构化材料列表。"
            )
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
        elif dietary_constraint_is_active(
            state.get("dietary_constraints")
        ) and not is_pure_knowledge_request(state["question"]):
            answer = render_dietary_safety_answer(observations)
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
