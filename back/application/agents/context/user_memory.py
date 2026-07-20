"""把长期用户记忆转换为 Agent 可消费的上下文 Observation。"""

from __future__ import annotations

import json
import re
from typing import Optional

from SafeMealAgent.back.application.agents.models import Observation
from SafeMealAgent.back.shared.types import JsonObject, to_json_object


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


def _safe_memory_value(memory: JsonObject) -> str:
    """从结构化字段重建文本，避免把持久化自由文本当成可信指令。"""

    memory_type = str(memory.get("memory_type", ""))
    key = re.sub(r"[\x00-\x1f\x7f]", "", str(memory.get("memory_key", ""))).strip()
    key = key[:255]
    template = _MEMORY_TEMPLATES.get(memory_type)
    return template.format(key=key) if template and key else ""


def build_user_memory_observation(
    user_memories: list[JsonObject],
) -> Optional[Observation]:
    """将活跃长期记忆包装成 Agent Trace 中的 Observation。

    Args:
        user_memories: UserMemoryService.load_agent_memories 返回的结构化记忆列表。

    Returns:
        一条 user_memory_context Observation；没有记忆时返回 None。

    这条 Observation 是用户画像上下文，不是外部工具调用结果。Planner 和
    Responder 可以据此做个性化推荐，但当前轮用户明确说明的约束优先级更高。
    """

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
