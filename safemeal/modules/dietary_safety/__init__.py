"""Dietary-safety module public API."""

from .domain import (
    Allergen,
    DietaryRestriction,
    Evidence,
    EvidenceBundle,
    EvidenceConflictPolicy,
    EvidenceSufficiencyPolicy,
    FailClosedPolicy,
    Ingredient,
    RecipeEligibilityPolicy,
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
    "EvidenceConflictPolicy",
    "EvidenceSufficiencyPolicy",
    "FailClosedPolicy",
    "Ingredient",
    "RecipeEligibilityPolicy",
    "RecipeSafetyInput",
    "SafetyDecision",
    "SafetyRisk",
    "SafetyStatus",
    "UserDietaryProfile",
]
