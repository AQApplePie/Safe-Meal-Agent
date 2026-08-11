"""Dietary-safety value objects and deterministic recipe evaluation.

This module deliberately has no dependency on Pydantic, FastAPI, LangGraph, an
ORM, or an external data source.  Infrastructure supplies structured evidence;
these rules remain the final authority for recipe eligibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .ingredient_terms import (
    DERIVED_SUFFIXES,
    NORMALISE_REMOVE_PATTERN,
    PREPARATION_PREFIXES,
    TOO_BROAD_TERMS,
)


class SafetyStatus(str, Enum):
    """Externally stable safety classifications."""

    SAFE = "safe"
    UNSAFE = "excluded"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Ingredient:
    name: str


@dataclass(frozen=True, slots=True)
class Allergen:
    name: str


@dataclass(frozen=True, slots=True)
class DietaryRestriction:
    term: str


@dataclass(frozen=True, slots=True)
class UserDietaryProfile:
    allergens: tuple[Allergen, ...] = ()
    restrictions: tuple[DietaryRestriction, ...] = ()

    @property
    def forbidden_terms(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.allergens) + tuple(
            item.term for item in self.restrictions
        )


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
        """Fail closed: only an explicit SAFE decision is recommendable."""

        return self.status is SafetyStatus.SAFE


def _unique(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in items if item.strip()))


def normalize_ingredient_name(value: str) -> str:
    """Normalize display-only differences without fuzzy substring matching."""

    return NORMALISE_REMOVE_PATTERN.sub("", str(value).strip().casefold())


def ingredient_matches_forbidden_term(ingredient: str, term: str) -> bool:
    """Match exact or explicitly supported ingredient derivations."""

    ingredient_name = normalize_ingredient_name(ingredient)
    forbidden = normalize_ingredient_name(term)
    if not ingredient_name or not forbidden:
        return False
    if ingredient_name == forbidden:
        return True
    if ingredient_name.endswith(forbidden):
        prefix = ingredient_name[: -len(forbidden)]
        return not prefix or prefix in PREPARATION_PREFIXES
    if ingredient_name.startswith(forbidden):
        suffix = ingredient_name[len(forbidden) :]
        return suffix in DERIVED_SUFFIXES
    if forbidden in TOO_BROAD_TERMS:
        return False
    return False


def match_forbidden_ingredients(
    ingredients: Iterable[str], forbidden_terms: Iterable[str]
) -> tuple[str, ...]:
    """Return structured ingredient names that violate the profile."""

    terms = tuple(forbidden_terms)
    return _unique(
        ingredient
        for ingredient in ingredients
        if any(ingredient_matches_forbidden_term(ingredient, term) for term in terms)
    )


def has_sufficient_evidence(bundle: EvidenceBundle) -> bool:
    """Return whether a safety decision has complete, usable source evidence."""

    return (
        bundle.core_source_available
        and bundle.ingredients_complete
        and bool(bundle.items)
    )


def has_conflicting_evidence(bundle: EvidenceBundle) -> bool:
    """Return whether independent safety sources disagree."""

    return bool(bundle.conflicting_sources)


class RecipeSafetyEvaluator:
    """Classify one recipe using deterministic ingredient and evidence rules."""

    def evaluate(self, safety_input: RecipeSafetyInput) -> SafetyDecision:
        matched = match_forbidden_ingredients(
            (item.name for item in safety_input.ingredients),
            safety_input.forbidden_terms,
        )
        if matched:
            return SafetyDecision(
                status=SafetyStatus.UNSAFE,
                risks=(
                    SafetyRisk(
                        code="forbidden_ingredient",
                        detail="、".join(matched),
                    ),
                ),
                matched_ingredients=matched,
                reason="候选菜证据中命中忌口/过敏食材，不能推荐。",
            )
        if not safety_input.evidence.core_source_available:
            return SafetyDecision(
                status=SafetyStatus.UNKNOWN,
                risks=(SafetyRisk("core_source_unavailable", "核心安全数据不可用"),),
                reason="核心安全数据不可用，按 fail-closed 处理。",
            )
        if has_conflicting_evidence(safety_input.evidence):
            return SafetyDecision(
                status=SafetyStatus.UNKNOWN,
                risks=(SafetyRisk("evidence_conflict", "安全证据相互冲突"),),
                reason="安全证据存在冲突，不能确认安全。",
            )
        if not has_sufficient_evidence(safety_input.evidence):
            return SafetyDecision(
                status=SafetyStatus.UNKNOWN,
                risks=(SafetyRisk("insufficient_evidence", "食材证据不完整"),),
                reason="候选菜缺少完整食材证据，不能确认安全。",
            )
        return SafetyDecision(
            status=SafetyStatus.SAFE,
            reason="候选菜的结构化食材证据未命中忌口/过敏食材。",
        )


__all__ = [
    "Allergen",
    "DietaryRestriction",
    "Evidence",
    "EvidenceBundle",
    "Ingredient",
    "RecipeSafetyEvaluator",
    "RecipeSafetyInput",
    "SafetyDecision",
    "SafetyRisk",
    "SafetyStatus",
    "UserDietaryProfile",
    "has_conflicting_evidence",
    "has_sufficient_evidence",
    "ingredient_matches_forbidden_term",
    "match_forbidden_ingredients",
    "normalize_ingredient_name",
]
