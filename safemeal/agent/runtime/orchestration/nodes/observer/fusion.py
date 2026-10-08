"""服务于 Observer 节点的多路证据融合。

Observer 将工具结果转换为 Observation 后调用本模块，对检索证据去重、排序，
再把更新后的 Agent 状态交给 Reflector；本模块本身不执行检索。
"""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Iterable

from safemeal.shared.types import JsonObject, to_json_object

from safemeal.agent.contracts.decisions import Observation


RETRIEVAL_TOOLS = frozenset(
    {
        "search_recipes",
        "get_recipe",
        "recommend_recipes",
        "search_knowledge",
        "dietary_safe_recipe_query",
    }
)

_SOURCE_WEIGHTS = {
    "search_recipes": 1.2,
    "get_recipe": 1.2,
    "recommend_recipes": 1.2,
    "dietary_safe_recipe_query": 1.15,
    "search_knowledge": 1.0,
}


def _items(observation: Observation) -> list[JsonObject]:
    data = observation.data
    if not isinstance(data, dict):
        return []
    if observation.tool_name == "search_knowledge":
        values = data.get("documents") or []
    elif observation.tool_name in {"search_recipes", "recommend_recipes"}:
        values = data.get("items") or []
    elif observation.tool_name == "dietary_safe_recipe_query":
        values = data.get("safe_recipes") or data.get("rows") or []
    elif observation.tool_name == "get_recipe":
        values = [data]
    else:
        values = []
    return [to_json_object(value) for value in values if value is not None]


def _content(item: JsonObject) -> str:
    for key in ("content", "text", "summary", "name", "title"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return json.dumps(item, ensure_ascii=False, default=str)[:6000]


def _identity(item: JsonObject, content: str) -> str:
    metadata_value = item.get("metadata")
    metadata: dict = metadata_value if isinstance(metadata_value, dict) else {}
    for key in ("document_id", "recipe_id", "chunk_id", "id"):
        value = item.get(key) or metadata.get(key)
        if value not in (None, ""):
            return f"{key}:{value}"
    normalized = " ".join(content.casefold().split())
    return "content:" + sha256(normalized.encode("utf-8")).hexdigest()


def fuse_retrieval_observations(
    observations: Iterable[Observation],
    *,
    top_k: int = 12,
    rrf_k: int = 60,
) -> Observation | None:
    """为 Observer 节点构建加权 RRF 融合后的 Observation。"""

    attempts = [item for item in observations if item.tool_name in RETRIEVAL_TOOLS]
    attempted_routes = list(dict.fromkeys(item.tool_name for item in attempts))
    if len(attempted_routes) < 2:
        return None

    successful_routes = list(
        dict.fromkeys(item.tool_name for item in attempts if item.ok and item.has_data)
    )
    failed_routes = list(
        dict.fromkeys(
            item.tool_name for item in attempts if not item.ok or not item.has_data
        )
    )
    fused: dict[str, JsonObject] = {}
    for observation in attempts:
        if not observation.ok:
            continue
        weight = _SOURCE_WEIGHTS.get(observation.tool_name, 1.0)
        for rank, item in enumerate(_items(observation), start=1):
            content = _content(item)
            if not content.strip():
                continue
            identity = _identity(item, content)
            score = weight / (rrf_k + rank)
            existing = fused.get(identity)
            if existing is None:
                fused[identity] = {
                    "evidence_id": identity,
                    "content": content,
                    "source": observation.tool_name,
                    "sources": [observation.tool_name],
                    "call_ids": [observation.call_id],
                    "fusion_score": score,
                    "raw": item,
                }
                continue
            existing["fusion_score"] = float(existing["fusion_score"]) + score
            existing["sources"] = list(
                dict.fromkeys([*existing["sources"], observation.tool_name])
            )
            existing["call_ids"] = list(
                dict.fromkeys([*existing["call_ids"], observation.call_id])
            )

    documents = sorted(
        fused.values(),
        key=lambda item: (-float(item["fusion_score"]), str(item["evidence_id"])),
    )[:top_k]
    data: JsonObject = {
        "strategy": "weighted_rrf",
        "successful_routes": successful_routes,
        "degraded_routes": failed_routes,
        "documents": documents,
        "count": len(documents),
    }
    return Observation(
        call_id="multi-route-fusion",
        tool_name="multi_route_retrieval",
        purpose="统一融合多路检索证据，并在部分来源失败时保留可用结果。",
        success_criteria="输出去重、可追踪且按加权RRF排序的证据。",
        ok=bool(documents),
        status="ok" if documents else "unavailable",
        has_data=bool(documents),
        summary=(
            f"融合{len(successful_routes)}路检索，得到{len(documents)}条证据；"
            f"降级来源：{failed_routes or '无'}"
        ),
        data=data,
        error=None if documents else "所有多路检索结果均不可用",
        error_code=None if documents else "multi_route_retrieval_unavailable",
        retryable=not documents,
    )


__all__ = ["RETRIEVAL_TOOLS", "fuse_retrieval_observations"]
