"""最终回答节点。

Responder 只依据 Observation 中的证据组织答案，不直接访问数据库或外部检索服务。
"""

from langchain_core.messages import AIMessage

from safemeal.application.observability import emit_answer_chunk, trace_span
from safemeal.modules.dietary_safety.answer import (
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
        with trace_span(
            "agent_node",
            "respond",
            {
                "evidence_sufficient": state.get("evidence_sufficient", False),
                "observation_count": len(state.get("observations", [])),
            },
        ) as span:
            observations = state.get("observations", [])
            if dietary_constraint_is_active(
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
                    "已达到本轮执行预算。当前可确认的证据摘要：\n- "
                    + "\n- ".join(usable)
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
            span.set_output(
                {
                    "answer": answer,
                    "sources": [item.model_dump() for item in output["sources"]],
                    "route": route,
                }
            )
            return output

    return respond
