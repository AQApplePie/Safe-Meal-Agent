"""饮食安全数据类型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SafetyStatus(str, Enum):

    SAFE = "safe"
    UNSAFE = "excluded"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Ingredient:
    name: str


@dataclass(frozen=True, slots=True)
class Evidence:
    source: str
    reference: str = ""


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    items: tuple[Evidence, ...] = ()
    ingredients_complete: bool = False
    core_source_available: bool = True
    conflicting_sources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SafetyRisk:
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class RecipeSafetyInput:
    recipe_name: str
    ingredients: tuple[Ingredient, ...]
    forbidden_terms: tuple[str, ...]
    evidence: EvidenceBundle


@dataclass(frozen=True, slots=True)
class SafetyDecision:
    status: SafetyStatus
    risks: tuple[SafetyRisk, ...] = ()
    matched_ingredients: tuple[str, ...] = ()
    reason: str = ""

    @property
    def eligible(self) -> bool:

        return self.status is SafetyStatus.SAFE
