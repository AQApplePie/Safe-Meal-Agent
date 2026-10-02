"""服务于 Responder 节点的证据来源归因。

Responder 在组织最终答案时调用本模块，将工具 Observation 转换为稳定的
``AnswerSource``，供 API 响应使用；本模块不访问外部系统，也不判断证据质量。
"""

from __future__ import annotations

from safemeal.application.contracts.agent.decisions import Observation
from safemeal.application.contracts.conversation.models import AnswerSource


def collect_answer_sources(observations: list[Observation]) -> list[AnswerSource]:
    """为 Responder 节点构建去重后的来源记录。"""

    sources: list[AnswerSource] = []
    for observation in observations:
        data = observation.data
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
                        tool=observation.tool_name,
                        call_id=observation.call_id,
                    )
                )
        if observation.tool_name == "dietary_safe_recipe_query":
            sources.append(
                AnswerSource(
                    source="neo4j:dietary-safety",
                    tool=observation.tool_name,
                    call_id=observation.call_id,
                )
            )
        elif observation.tool_name in {
            "search_recipes",
            "get_recipe",
            "recommend_recipes",
        }:
            candidates = data.get("items", []) if isinstance(data, dict) else []
            attributed = False
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                source = candidate.get("source_url") or candidate.get("source_title")
                if source:
                    attributed = True
                    sources.append(
                        AnswerSource(
                            source=str(source),
                            tool=observation.tool_name,
                            call_id=observation.call_id,
                        )
                    )
            if not attributed:
                sources.append(
                    AnswerSource(
                        source="mysql:recipes",
                        tool=observation.tool_name,
                        call_id=observation.call_id,
                    )
                )
        elif observation.tool_name == "generate_recipe":
            sources.append(
                AnswerSource(
                    source="model:structured_recipe",
                    tool=observation.tool_name,
                    call_id=observation.call_id,
                )
            )
        elif observation.tool_name == "dietary_safety_filter":
            evidence_call_ids = [
                str(call_id)
                for bucket in ("safe_recipes", "excluded_recipes", "unknown_recipes")
                for recipe in data.get(bucket, []) or []
                if isinstance(recipe, dict)
                for call_id in recipe.get("evidence_call_ids", []) or []
            ]
            sources.append(
                AnswerSource(
                    source="dietary_safety_filter",
                    tool=observation.tool_name,
                    call_id=observation.call_id,
                    evidence_call_ids=sorted(set(evidence_call_ids)),
                )
            )

    unique: list[AnswerSource] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for source in sources:
        key = (source.source, source.tool, source.query)
        if key not in seen:
            seen.add(key)
            unique.append(source)
    return unique


__all__ = ["collect_answer_sources"]
