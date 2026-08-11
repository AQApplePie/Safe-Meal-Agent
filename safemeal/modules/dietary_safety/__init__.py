"""Dietary-safety module public API."""

from .recipe_safety import (
    Allergen,
    DietaryRestriction,
    Evidence,
    EvidenceBundle,
    Ingredient,
    RecipeSafetyEvaluator,
    RecipeSafetyInput,
    SafetyDecision,
    SafetyRisk,
    SafetyStatus,
    UserDietaryProfile,
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
]
