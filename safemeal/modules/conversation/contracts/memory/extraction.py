"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from safemeal.shared.types import JsonObject


ExtractedMemoryType: TypeAlias = Literal[
    "dietary_allergy",
    "dietary_restriction",
    "taste_dislike",
    "taste_preference",
    "cooking_constraint",
    "cooking_equipment",
    "cooking_time",
    "health_goal",
]


@dataclass(frozen=True, slots=True)
class MemoryCandidate:

    memory_type: ExtractedMemoryType
    key: str
    value: str
    confidence: float
    metadata: JsonObject | None = None


@dataclass(frozen=True, slots=True)
class MemoryExtractionResult:

    candidates: tuple[MemoryCandidate, ...] = ()
    retracted_dietary_keys: tuple[str, ...] = ()


__all__ = ["ExtractedMemoryType", "MemoryCandidate", "MemoryExtractionResult"]
