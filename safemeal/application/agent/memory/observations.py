"""Safe conversion of persisted memory records into Agent observations.

Persisted free text is untrusted input. This module reconstructs supported memory
sentences from typed fields, bounds their size and exposes only the attributes the
Agent needs. It performs no storage access and therefore remains deterministic.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from safemeal.application.contracts.agent.decisions import Observation
from safemeal.application.contracts.dietary_safety.constraints import DietaryConstraint
from safemeal.shared.types import JsonObject, to_json_object


_MEMORY_TEMPLATES = {
    "dietary_allergy": "用户对{key}过敏。",
    "dietary_restriction": "用户需要避开{key}。",
    "taste_dislike": "用户不喜欢{key}。",
    "taste_preference": "用户偏好{key}。",
    "cooking_constraint": "用户的烹饪限制是{key}。",
    "cooking_equipment": "用户可使用{key}。",
    "cooking_time": "用户倾向在{key}内完成烹饪。",
    "health_goal": "用户关注{key}。",
}


def build_dietary_context_observation(
    constraint: DietaryConstraint,
) -> Optional[Observation]:
    """Wrap active hard constraints as immutable planning evidence."""

    if not constraint.active:
        return None
    data = to_json_object(constraint)
    summary = (
        "当前有效忌口/过敏约束："
        f"原始食材={constraint.raw_ingredients}；"
        f"禁忌食材展开={constraint.excluded_ingredients}；"
        f"严格度={constraint.strictness}。"
    )
    return Observation(
        call_id="dietary_context",
        tool_name="dietary_context",
        purpose="记录从当前问题和历史对话继承得到的忌口/过敏约束。",
        success_criteria="后续规划、反思和最终回答必须遵守这些禁忌食材。",
        ok=True,
        has_data=True,
        summary=summary if len(summary) <= 1200 else summary[:1200] + "...",
        data=data,
    )


def _safe_memory_value(memory: JsonObject) -> str:
    """Rebuild prompt text from typed fields instead of stored free text."""

    memory_type = str(memory.get("memory_type", ""))
    key = re.sub(r"[\x00-\x1f\x7f]", "", str(memory.get("memory_key", ""))).strip()
    key = key[:255]
    template = _MEMORY_TEMPLATES.get(memory_type)
    return template.format(key=key) if template and key else ""


def build_user_memory_observation(
    user_memories: list[JsonObject],
) -> Optional[Observation]:
    """Group supported long-term memories into bounded, source-aware evidence."""

    if not user_memories:
        return None
    grouped: dict[str, list[JsonObject]] = {}
    for memory in user_memories:
        safe_value = _safe_memory_value(memory)
        if not safe_value:
            continue
        safe_memory = {
            "id": memory.get("id"),
            "memory_type": memory.get("memory_type"),
            "memory_key": memory.get("memory_key"),
            "memory_value": safe_value,
            "confidence": memory.get("confidence"),
        }
        grouped.setdefault(str(memory.get("memory_type")), []).append(safe_memory)
    if not grouped:
        return None
    compact = {
        memory_type: [
            {
                "id": item.get("id"),
                "key": item.get("memory_key"),
                "value": _safe_memory_value(item) or item.get("memory_value"),
                "confidence": item.get("confidence"),
            }
            for item in items
        ]
        for memory_type, items in grouped.items()
    }
    summary = json.dumps(compact, ensure_ascii=False, default=str)
    return Observation(
        call_id="user_memory_context",
        tool_name="user_memory_context",
        purpose="提供跨会话长期用户画像，用于个性化推荐和饮食安全约束继承。",
        success_criteria="当前轮没有明确覆盖/否定时，规划和回答应遵守这些用户记忆。",
        ok=True,
        has_data=True,
        summary=summary if len(summary) <= 1200 else summary[:1200] + "...",
        data=to_json_object(
            {
                "memories": [item for items in grouped.values() for item in items],
                "grouped": compact,
            }
        ),
    )


__all__ = [
    "build_dietary_context_observation",
    "build_user_memory_observation",
]
