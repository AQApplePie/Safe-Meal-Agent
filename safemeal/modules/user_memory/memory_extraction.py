"""长期记忆规则抽取器。

本模块只回答一个问题：用户这句话里有没有值得长期保存的明确事实。
它不负责数据库事务、不负责 upsert、不负责 HTTP 响应。
"""

from __future__ import annotations

import re
from typing import Iterable

from safemeal.modules.dietary_safety.dietary_constraints import (
    extract_dietary_constraint,
)
from safemeal.modules.dietary_safety.ingredient_terms import INGREDIENT_ALIASES
from safemeal.shared.types import JsonObject
from safemeal.modules.user_memory.memory_models import (
    ExtractedMemoryType,
    MemoryCandidate,
    MemoryExtractionResult,
)


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


def _unique(values: Iterable[str]) -> list[str]:
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


def _split_memory_keys(value: str) -> list[str]:
    return _unique(
        key
        for key in (_clean_memory_key(part) for part in _SPLIT_PATTERN.split(value))
        if 1 <= len(key) <= 12
    )


class UserMemoryExtractor:
    """把用户消息抽取为候选长期记忆。"""

    def extract(self, message: str) -> MemoryExtractionResult:
        candidates: list[MemoryCandidate] = []
        candidates.extend(self._extract_dietary_memories(message))
        candidates.extend(self._extract_preference_memories(message))
        candidates.extend(self._extract_cooking_memories(message))
        candidates.extend(self._extract_health_memories(message))

        deduped: dict[tuple[str, str], MemoryCandidate] = {}
        for candidate in candidates:
            deduped[(candidate.memory_type, candidate.key)] = candidate
        return MemoryExtractionResult(
            candidates=tuple(deduped.values()),
            retracted_dietary_keys=tuple(self.extract_dietary_retractions(message)),
        )

    def extract_dietary_retractions(self, message: str) -> list[str]:
        """Return explicitly retracted allergy/restriction keys.

        Retractions are deliberately conservative: a historical hard constraint is
        archived only when the same ingredient occurs in an explicit negation pattern.
        """

        retracted: list[str] = []
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
        memory_type: ExtractedMemoryType,
        memory_key: str,
        memory_value: str,
        confidence: float,
        memory_metadata: JsonObject | None = None,
    ) -> MemoryCandidate:
        return MemoryCandidate(
            memory_type=memory_type,
            key=memory_key,
            value=memory_value,
            confidence=confidence,
            metadata=memory_metadata,
        )

    def _extract_dietary_memories(self, message: str) -> list[MemoryCandidate]:
        constraint = extract_dietary_constraint(message)
        if not constraint.active:
            return []

        memory_type: ExtractedMemoryType = (
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
                    memory_type=memory_type,
                    memory_key=key,
                    memory_value=f"用户{key}{label}。",
                    confidence=confidence,
                    memory_metadata={
                        "trigger_terms": constraint.trigger_terms,
                        "excluded_ingredients": constraint.excluded_ingredients,
                        "strictness": constraint.strictness,
                    },
                )
            )
        return memories

    def _extract_preference_memories(self, message: str) -> list[MemoryCandidate]:
        memories: list[MemoryCandidate] = []
        patterns: tuple[tuple[str, ExtractedMemoryType, str, float], ...] = (
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
                            memory_type=memory_type,
                            memory_key=key,
                            memory_value=template.format(key=key),
                            confidence=confidence,
                        )
                    )
        return memories

    def _extract_cooking_memories(self, message: str) -> list[MemoryCandidate]:
        memories: list[MemoryCandidate] = []
        for equipment in _EQUIPMENT_TERMS:
            if f"没有{equipment}" in message or f"没{equipment}" in message:
                memories.append(
                    self._memory(
                        memory_type="cooking_constraint",
                        memory_key=f"无{equipment}",
                        memory_value=f"用户没有{equipment}。",
                        confidence=0.9,
                    )
                )
            elif f"只有{equipment}" in message or f"有{equipment}" in message:
                memories.append(
                    self._memory(
                        memory_type="cooking_equipment",
                        memory_key=equipment,
                        memory_value=f"用户可使用{equipment}。",
                        confidence=0.85,
                    )
                )

        for match in re.finditer(r"(\d{1,3})\s*分钟(?:内|以内|左右)?", message):
            minutes = int(match.group(1))
            if 1 <= minutes <= 240:
                memories.append(
                    self._memory(
                        memory_type="cooking_time",
                        memory_key=f"{minutes}分钟",
                        memory_value=f"用户倾向于 {minutes} 分钟左右完成烹饪。",
                        confidence=0.75,
                    )
                )
        return memories

    def _extract_health_memories(self, message: str) -> list[MemoryCandidate]:
        return [
            self._memory(
                memory_type="health_goal",
                memory_key=goal,
                memory_value=f"用户关注{goal}。",
                confidence=0.8,
            )
            for goal in _HEALTH_GOALS
            if goal in message
        ]
