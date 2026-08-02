"""Observation 节点。

将不同工具返回的原始结果规整为统一观察记录，并在饮食安全场景下生成可审计的
过滤视图。
"""

import json

from safemeal.application.agents.context import (
    build_dietary_safety_observation,
)
from safemeal.application.observability import trace_span
from safemeal.application.agents.retrieval_fusion import fuse_retrieval_observations
from safemeal.shared.types import JsonValue, to_json_value

from ..models import Observation
from ..state import AgentState, AgentStateUpdate


def _has_data(data: JsonValue) -> bool:
    if data is None:
        return False
    if isinstance(data, str):
        return bool(data.strip())
    if isinstance(data, (list, tuple, set)):
        return bool(data)
    if isinstance(data, dict):
        for key in ("rows", "documents", "items"):
            if key in data:
                return bool(data[key])
        if "response" in data:
            return bool(str(data["response"]).strip())
        if "tables" in data:
            return bool(data["tables"])
        if "labels" in data or "relationship_types" in data:
            return bool(data.get("labels") or data.get("relationship_types"))
        return bool(data)
    return True


def _summary(data: JsonValue, error: str | None) -> str:
    if error:
        return f"工具执行失败：{error}"
    text = json.dumps(data, ensure_ascii=False, default=str)
    return text if len(text) <= 800 else text[:800] + "..."


def _compact_data(data: JsonValue, depth: int = 0, parent_key: str = "") -> JsonValue:
    """限制状态体积，同时保留Recipe固定聚合中的食材和营养字段。"""
    # RecipeSearchResult -> items -> Recipe -> ingredients -> quantity ->
    # Ingredient -> nutrition is seven levels deep. A smaller limit turns the
    # typed ingredient object into a string and destroys safety evidence.
    if depth >= 8:
        return str(data)[:500]
    if isinstance(data, str):
        return data if len(data) <= 2400 else data[:2400] + "..."
    if isinstance(data, list):
        limit = (
            20 if "ingredient" in parent_key.casefold() or "食材" in parent_key else 8
        )
        compacted = [
            _compact_data(item, depth + 1, parent_key) for item in data[:limit]
        ]
        if len(data) > limit:
            compacted.append({"truncated_items": len(data) - limit})
        return to_json_value(compacted)
    if isinstance(data, dict):
        return to_json_value(
            {
                str(key): _compact_data(value, depth + 1, str(key))
                for key, value in list(data.items())[:36]
            }
        )
    return to_json_value(data)


async def observe(state: AgentState) -> AgentStateUpdate:
    with trace_span(
        "agent_node",
        "observe",
        {"tool_result_count": len(state.get("tool_results", []))},
    ) as span:
        calls = {call.id: call for call in state.get("pending_calls", [])}
        observations = []
        for result in state.get("tool_results", []):
            call = calls.get(result.call_id)
            compact_data = _compact_data(result.data)
            observations.append(
                Observation(
                    call_id=result.call_id,
                    tool_name=result.tool_name,
                    purpose=call.purpose if call else "",
                    success_criteria=call.success_criteria if call else "",
                    ok=result.ok,
                    status=result.status,
                    has_data=result.ok and _has_data(compact_data),
                    summary=_summary(compact_data, result.error),
                    data=compact_data,
                    error=result.error,
                    error_code=result.error_code,
                    retryable=result.retryable,
                )
            )
        all_observations = list(state.get("observations", [])) + observations
        all_observations = [
            item
            for item in all_observations
            if item.tool_name != "multi_route_retrieval"
        ]
        fused_retrieval = fuse_retrieval_observations(all_observations)
        if fused_retrieval is not None:
            all_observations.append(fused_retrieval)
        dietary_observation = build_dietary_safety_observation(
            constraint_payload=state.get("dietary_constraints"),
            observations=all_observations,
        )
        if dietary_observation is not None:
            # 每次 observe 都重新计算一次过滤视图，因此先移除旧的过滤 Observation，
            # 避免 Reflection/Responder 同时看到过期和最新的 safe/excluded/unknown。
            all_observations = [
                item
                for item in all_observations
                if item.tool_name != "dietary_safety_filter"
            ]
            all_observations.append(dietary_observation)
        output: AgentStateUpdate = {
            "observations": all_observations,
            "pending_calls": [],
            "tool_results": [],
        }
        span.set_output(
            {
                "new_observations": [item.model_dump() for item in observations],
                "dietary_safety_applied": dietary_observation is not None,
                "total_observation_count": len(output["observations"]),
            }
        )
        return output
