"""最终回答节点。

Responder 只依据 Observation 中的证据组织答案，不直接访问数据库或外部检索服务。
"""

from langchain_core.messages import AIMessage

from SafeMealAgent.back.application.observability import emit_answer_chunk, trace_span

from ..decision_engine import DecisionEngine
from ..routing_policy import is_pure_knowledge_request
from SafeMealAgent.back.shared.contracts.common import AnswerSource, RouterInfo
from ..models import Observation
from ..state import AgentState, AgentStateUpdate


def _dietary_constraint_active(state: AgentState) -> bool:
    constraint = state.get("dietary_constraints") or {}
    return bool(isinstance(constraint, dict) and constraint.get("active"))


def _dietary_safe_answer(observations: list[Observation]) -> str:
    """Render a safety answer exclusively from deterministic classified evidence."""

    safety = next(
        (
            item.data
            for item in reversed(observations)
            if item.tool_name == "dietary_safety_filter" and isinstance(item.data, dict)
        ),
        None,
    )
    if not isinstance(safety, dict):
        return (
            "当前没有取得足够的结构化食材证据，无法确认菜品满足你的忌口或过敏"
            "要求。为避免风险，我暂不做具体推荐。"
        )

    safe_records = [
        item for item in safety.get("safe_recipes", []) if isinstance(item, dict)
    ]
    excluded_records = [
        item for item in safety.get("excluded_recipes", []) if isinstance(item, dict)
    ]
    unknown_records = [
        item for item in safety.get("unknown_recipes", []) if isinstance(item, dict)
    ]
    lines: list[str] = []
    if safe_records:
        lines.append("根据当前结构化食材证据，已确认以下菜品未命中禁忌食材：")
        for record in safe_records[:5]:
            ingredients = [str(item) for item in record.get("ingredients", []) or []]
            detail = f"（已核对：{'、'.join(ingredients)}）" if ingredients else ""
            lines.append(f"- {record.get('name', '未命名菜品')}{detail}")
    else:
        lines.append("当前证据尚未确认任何可以安全推荐的菜品。")

    if excluded_records:
        lines.append("以下菜品命中禁忌食材，不能推荐：")
        for record in excluded_records[:5]:
            matched = [
                str(item)
                for item in record.get("matched_forbidden_ingredients", []) or []
            ]
            detail = f"（命中：{'、'.join(matched)}）" if matched else ""
            lines.append(f"- {record.get('name', '未命名菜品')}{detail}")

    if unknown_records:
        names = "、".join(
            str(item.get("name", "未命名菜品")) for item in unknown_records[:5]
        )
        lines.append(f"证据不足、暂不能确认安全：{names}。")
    missing = [str(item) for item in safety.get("missing_information", []) or []]
    if missing and not safe_records:
        lines.append("仍缺少：" + "；".join(missing[:3]))
    lines.append("如属严重过敏，请同时核对调味料标签和加工过程中的交叉接触风险。")
    return "\n".join(lines)


def _collect_sources(observations: list[Observation]) -> list[AnswerSource]:
    sources: list[AnswerSource] = []
    for item in observations:
        data = item.data
        if not isinstance(data, dict):
            continue
        for document in data.get("documents", []) or []:
            if not isinstance(document, dict):
                continue
            metadata = document.get("metadata") or {}
            source = document.get("source") or metadata.get("source")
            if source:
                sources.append(
                    AnswerSource(
                        source=str(source),
                        tool=item.tool_name,
                        call_id=item.call_id,
                    )
                )
        if item.tool_name == "neo4j_readonly_query" and data.get("cypher"):
            sources.append(
                AnswerSource(
                    source="neo4j",
                    tool=item.tool_name,
                    call_id=item.call_id,
                    query=str(data["cypher"]),
                )
            )
        elif item.tool_name == "dietary_safe_recipe_query":
            sources.append(
                AnswerSource(
                    source="neo4j:dietary-safety",
                    tool=item.tool_name,
                    call_id=item.call_id,
                )
            )
        elif item.tool_name == "lightrag_search":
            sources.append(
                AnswerSource(
                    source="lightrag",
                    tool=item.tool_name,
                    call_id=item.call_id,
                )
            )
        elif item.tool_name in {"search_recipes", "get_recipe", "recommend_recipes"}:
            sources.append(
                AnswerSource(
                    source="mysql:recipes",
                    tool=item.tool_name,
                    call_id=item.call_id,
                )
            )
        elif item.tool_name == "generate_recipe":
            sources.append(
                AnswerSource(
                    source="model:structured_recipe",
                    tool=item.tool_name,
                    call_id=item.call_id,
                )
            )
        elif item.tool_name == "dietary_safety_filter":
            evidence_call_ids: list[str] = []
            for bucket in ("safe_recipes", "excluded_recipes", "unknown_recipes"):
                for record in data.get(bucket, []) or []:
                    if not isinstance(record, dict):
                        continue
                    evidence_call_ids.extend(
                        str(call_id)
                        for call_id in record.get("evidence_call_ids", []) or []
                    )
            sources.append(
                AnswerSource(
                    source="dietary_safety_filter",
                    tool=item.tool_name,
                    call_id=item.call_id,
                    evidence_call_ids=sorted(set(evidence_call_ids)),
                )
            )

    unique: list[AnswerSource] = []
    seen = set()
    for source in sources:
        key = (source.source, source.tool, source.query)
        if key not in seen:
            seen.add(key)
            unique.append(source)
    return unique


def create_responder_node(engine: DecisionEngine):
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
            if _dietary_constraint_active(state) and not is_pure_knowledge_request(
                state["question"]
            ):
                answer = _dietary_safe_answer(observations)
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
                answer = await engine.answer(
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
                type="agent-tool-loop",
                logic=(
                    state.get("reflection_rationale")
                    or state.get("planning_rationale")
                    or route
                ),
            )
            output: AgentStateUpdate = {
                "messages": [AIMessage(content=answer)],
                "sources": _collect_sources(observations),
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
