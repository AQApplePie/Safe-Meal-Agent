"""Contracts for deterministic recipe-name lookup."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from safemeal.application.contracts.workflow.request_frame import MenuCategory


class RecipeCandidate(BaseModel):
    """Normalized, read-only recipe evidence from any source."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    ingredients: tuple[dict[str, str], ...] = ()
    steps: str = ""
    nutrition: dict[str, str | float | int] | None = None
    total_time_minutes: int | None = Field(default=None, ge=0)
    servings: int | None = Field(default=None, ge=1)
    source_type: Literal[
        "canonical_database", "local_json", "session", "wikibooks", "wikipedia"
    ]
    source_url: str | None = None
    source_title: str
    confidence: float = Field(ge=0, le=1)
    persistent: bool = False
    ingredients_complete: bool = False

    @property
    def source(self) -> str:
        return self.source_url or f"{self.source_type}:{self.source_title}"


class RecipeLookupResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["FOUND", "NOT_FOUND", "ERROR"]
    query: str
    match_type: Literal["exact", "normalized", "lexical", "none"] = "none"
    provider: str
    items: tuple[RecipeCandidate, ...] = ()
    error: str | None = None


# Compatibility name for callers introduced with the original local JSON lookup.
RecipeEvidence = RecipeCandidate


class MenuRecipeCandidate(BaseModel):
    """Lightweight evidence returned while filling a composite menu quota."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: int | None = None
    name: str
    categories: tuple[MenuCategory, ...]
    main_ingredients: tuple[str, ...] = ()
    # Full ingredients are retained for the independent final safety review;
    # ``main_ingredients`` remains the concise chat-display projection.
    ingredients: tuple[str, ...] = ()
    ingredients_complete: bool = True
    source_type: Literal["canonical_database", "local_json", "wikibooks"]
    source_title: str
    safety_status: Literal["eligible", "unknown"] = "eligible"
