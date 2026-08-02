"""长期记忆规则抽取器。

本模块只回答一个问题：用户这句话里有没有值得长期保存的明确事实。
它不负责数据库事务、不负责 upsert、不负责 HTTP 响应。
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional

from safemeal.modules.dietary_safety.application import extract_dietary_constraint
from safemeal.modules.dietary_safety.terms import INGREDIENT_ALIASES
from safemeal.shared.contracts.memory import MemoryType, UserMemoryCreate
from safemeal.shared.types import JsonObject


_SPLIT_PATTERN = re.compile(r"[、,，/和及与\s]+")
_CLEAN_EDGE_CHARS = "：:的类等一点一些菜食物口味风格偏好"
_EQUIPMENT_TERMS = (
    "空气炸锅",
    "烤箱",
    "电饭煲",
    "微波炉",
    "平底锅",
    "蒸锅",
    "破壁机",
)
_HEALTH_GOALS = ("减脂", "控糖", "低盐", "低脂", "高蛋白", "增肌", "少油")


def _unique(values: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        item = str(value).strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _clean_memory_key(value: str) -> str:
    return value.strip().strip(_CLEAN_EDGE_CHARS).strip()


def _split_memory_keys(value: str) -> List[str]:
    return _unique(
        key
        for key in (_clean_memory_key(part) for part in _SPLIT_PATTERN.split(value))
        if 1 <= len(key) <= 12
    )


class MemoryExtractor:
    """把用户消息抽取为候选长期记忆。"""

    def extract(
        self,
        *,
        user_id: str,
        message: str,
        source_session_id: Optional[str] = None,
        source_message_id: Optional[str] = None,
    ) -> List[UserMemoryCreate]:
        candidates: List[UserMemoryCreate] = []
        candidates.extend(
            self._extract_dietary_memories(
                user_id=user_id,
                message=message,
                source_session_id=source_session_id,
                source_message_id=source_message_id,
            )
        )
        candidates.extend(
            self._extract_preference_memories(
                user_id=user_id,
                message=message,
                source_session_id=source_session_id,
                source_message_id=source_message_id,
            )
        )
        candidates.extend(
            self._extract_cooking_memories(
                user_id=user_id,
                message=message,
                source_session_id=source_session_id,
                source_message_id=source_message_id,
            )
        )
        candidates.extend(
            self._extract_health_memories(
                user_id=user_id,
                message=message,
                source_session_id=source_session_id,
                source_message_id=source_message_id,
            )
        )

        deduped: Dict[tuple[str, str], UserMemoryCreate] = {}
        for candidate in candidates:
            deduped[(candidate.memory_type, candidate.memory_key)] = candidate
        return list(deduped.values())

    def extract_dietary_retractions(self, message: str) -> List[str]:
        """Return explicitly retracted allergy/restriction keys.

        Retractions are deliberately conservative: a historical hard constraint is
        archived only when the same ingredient occurs in an explicit negation pattern.
        """

        retracted: List[str] = []
        for ingredient in INGREDIENT_ALIASES:
            escaped = re.escape(ingredient)
            patterns = (
                rf"不再(?:对)?{escaped}(?:过敏|忌口)",
                rf"对{escaped}(?:已经)?不过敏",
                rf"{escaped}(?:已经)?不再是?(?:过敏原|忌口)",
                rf"不再(?:忌口|避开|不吃){escaped}",
            )
            if any(re.search(pattern, message) for pattern in patterns):
                retracted.append(ingredient)
        return _unique(retracted)

    def _memory(
        self,
        *,
        user_id: str,
        memory_type: MemoryType,
        memory_key: str,
        memory_value: str,
        confidence: float,
        source_session_id: Optional[str],
        source_message_id: Optional[str],
        memory_metadata: Optional[JsonObject] = None,
    ) -> UserMemoryCreate:
        return UserMemoryCreate(
            user_id=user_id,
            memory_type=memory_type,
            memory_key=memory_key,
            memory_value=memory_value,
            confidence=confidence,
            source="explicit_user_statement",
            source_session_id=source_session_id,
            source_message_id=source_message_id,
            memory_metadata=memory_metadata,
        )

    def _extract_dietary_memories(
        self,
        *,
        user_id: str,
        message: str,
        source_session_id: Optional[str],
        source_message_id: Optional[str],
    ) -> List[UserMemoryCreate]:
        constraint = extract_dietary_constraint(message)
        if not constraint.active:
            return []

        memory_type: MemoryType = (
            "dietary_allergy" if "过敏" in message else "dietary_restriction"
        )
        label = "过敏" if memory_type == "dietary_allergy" else "不能吃/需要避开"
        confidence = 1.0 if memory_type == "dietary_allergy" else 0.95
        memories = []
        for ingredient in constraint.raw_ingredients:
            key = _clean_memory_key(ingredient)
            if not key:
                continue
            memories.append(
                self._memory(
                    user_id=user_id,
                    memory_type=memory_type,
                    memory_key=key,
                    memory_value=f"用户{key}{label}。",
                    confidence=confidence,
                    source_session_id=source_session_id,
                    source_message_id=source_message_id,
                    memory_metadata={
                        "trigger_terms": constraint.trigger_terms,
                        "excluded_ingredients": constraint.excluded_ingredients,
                        "strictness": constraint.strictness,
                    },
                )
            )
        return memories

    def _extract_preference_memories(
        self,
        *,
        user_id: str,
        message: str,
        source_session_id: Optional[str],
        source_message_id: Optional[str],
    ) -> List[UserMemoryCreate]:
        memories: List[UserMemoryCreate] = []
        patterns: tuple[tuple[str, MemoryType, str, float], ...] = (
            (
                r"(?:我|本人)?(?:不喜欢|不爱吃|讨厌)([^，。；;,.]{1,20})",
                "taste_dislike",
                "用户不喜欢{key}。",
                0.85,
            ),
            (
                r"(?:我|本人)?(?:喜欢|爱吃|偏好)([^，。；;,.]{1,20})",
                "taste_preference",
                "用户偏好{key}。",
                0.8,
            ),
        )
        for pattern, memory_type, template, confidence in patterns:
            for match in re.finditer(pattern, message):
                for key in _split_memory_keys(match.group(1)):
                    memories.append(
                        self._memory(
                            user_id=user_id,
                            memory_type=memory_type,
                            memory_key=key,
                            memory_value=template.format(key=key),
                            confidence=confidence,
                            source_session_id=source_session_id,
                            source_message_id=source_message_id,
                        )
                    )
        return memories

    def _extract_cooking_memories(
        self,
        *,
        user_id: str,
        message: str,
        source_session_id: Optional[str],
        source_message_id: Optional[str],
    ) -> List[UserMemoryCreate]:
        memories: List[UserMemoryCreate] = []
        for equipment in _EQUIPMENT_TERMS:
            if f"没有{equipment}" in message or f"没{equipment}" in message:
                memories.append(
                    self._memory(
                        user_id=user_id,
                        memory_type="cooking_constraint",
                        memory_key=f"无{equipment}",
                        memory_value=f"用户没有{equipment}。",
                        confidence=0.9,
                        source_session_id=source_session_id,
                        source_message_id=source_message_id,
                    )
                )
            elif f"只有{equipment}" in message or f"有{equipment}" in message:
                memories.append(
                    self._memory(
                        user_id=user_id,
                        memory_type="cooking_equipment",
                        memory_key=equipment,
                        memory_value=f"用户可使用{equipment}。",
                        confidence=0.85,
                        source_session_id=source_session_id,
                        source_message_id=source_message_id,
                    )
                )

        for match in re.finditer(r"(\d{1,3})\s*分钟(?:内|以内|左右)?", message):
            minutes = int(match.group(1))
            if 1 <= minutes <= 240:
                memories.append(
                    self._memory(
                        user_id=user_id,
                        memory_type="cooking_time",
                        memory_key=f"{minutes}分钟",
                        memory_value=f"用户倾向于 {minutes} 分钟左右完成烹饪。",
                        confidence=0.75,
                        source_session_id=source_session_id,
                        source_message_id=source_message_id,
                    )
                )
        return memories

    def _extract_health_memories(
        self,
        *,
        user_id: str,
        message: str,
        source_session_id: Optional[str],
        source_message_id: Optional[str],
    ) -> List[UserMemoryCreate]:
        return [
            self._memory(
                user_id=user_id,
                memory_type="health_goal",
                memory_key=goal,
                memory_value=f"用户关注{goal}。",
                confidence=0.8,
                source_session_id=source_session_id,
                source_message_id=source_message_id,
            )
            for goal in _HEALTH_GOALS
            if goal in message
        ]
