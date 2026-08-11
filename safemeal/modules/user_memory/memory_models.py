"""Pure domain values produced while extracting user memories."""

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
    """A user fact worth remembering, without persistence identity or provenance."""

    memory_type: ExtractedMemoryType
    key: str
    value: str
    confidence: float
    metadata: JsonObject | None = None


@dataclass(frozen=True, slots=True)
class MemoryExtractionResult:
    """Domain outcome of analysing one user utterance."""

    candidates: tuple[MemoryCandidate, ...] = ()
    retracted_dietary_keys: tuple[str, ...] = ()


__all__ = ["ExtractedMemoryType", "MemoryCandidate", "MemoryExtractionResult"]
