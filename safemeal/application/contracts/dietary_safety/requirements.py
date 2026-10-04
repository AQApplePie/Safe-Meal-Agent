"""User requirements and recipe review results shared across workflow boundaries."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .constraints import DietaryConstraint, RecipeSafetyRecord
from .control_plane import ResolvedConstraints


class DietaryPreference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal[
        "taste",
        "avoid_ingredient",
        "include_ingredient",
        "max_minutes",
        "dietary_type",
        "equipment",
        "other",
    ]
    value: str = Field(min_length=1, max_length=200)
    required: bool = False
    source: Literal["input", "history", "memory", "provided"]

    @model_validator(mode="after")
    def validate_value(self):
        if self.kind == "max_minutes" and (
            not self.value.isdigit() or not 1 <= int(self.value) <= 10080
        ):
            raise ValueError("max_minutes must be between 1 and 10080")
        if self.kind == "dietary_type" and self.value not in {
            "vegetarian",
            "vegan",
            "pescatarian",
        }:
            raise ValueError("unsupported dietary type")
        return self


class DietaryRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allergies: DietaryConstraint = Field(
        default_factory=lambda: DietaryConstraint(active=False)
    )
    restrictions: DietaryConstraint = Field(
        default_factory=lambda: DietaryConstraint(active=False)
    )
    preferences: list[DietaryPreference] = Field(default_factory=list)
    resolved: ResolvedConstraints = Field(default_factory=ResolvedConstraints)


class PreferenceAssessment(BaseModel):
    preference: DietaryPreference
    status: Literal["satisfied", "not_satisfied", "unknown"]
    reason: str


class RecipeReview(BaseModel):
    name: str
    decision: Literal["passed", "excluded", "unknown"]
    allergy_status: Literal["safe", "excluded", "unknown"]
    preference_status: Literal[
        "satisfied", "partial", "not_satisfied", "unknown", "not_applicable"
    ]
    preferences: list[PreferenceAssessment] = Field(default_factory=list)
    evidence: RecipeSafetyRecord


class DietaryReviewResult(BaseModel):
    recipes: list[RecipeReview] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
