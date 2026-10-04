"""Deterministic ingredient matching and recipe safety classification.

This module deliberately has no dependency on Pydantic, FastAPI, LangGraph, an
ORM, or an external data source.  Infrastructure supplies structured evidence;
these rules remain the final authority for recipe eligibility.
"""

from __future__ import annotations

from safemeal.application.contracts.dietary_safety.models import (
    SafetyStatus,
    EvidenceBundle,
    SafetyRisk,
    RecipeSafetyInput,
    SafetyDecision,
)

from typing import Iterable

from safemeal.application.service.dietary_safety.ingredient_terms import (
    DERIVED_SUFFIXES,
    NORMALISE_REMOVE_PATTERN,
    PREPARATION_PREFIXES,
    TOO_BROAD_TERMS,
)


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
    "RecipeSafetyEvaluator",
    "has_conflicting_evidence",
    "has_sufficient_evidence",
    "ingredient_matches_forbidden_term",
    "match_forbidden_ingredients",
    "normalize_ingredient_name",
]
