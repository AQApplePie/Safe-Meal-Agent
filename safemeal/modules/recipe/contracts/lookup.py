"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from safemeal.shared.contracts.request_frame import MenuCategory


class RecipeCandidate(BaseModel):

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



RecipeEvidence = RecipeCandidate


class MenuRecipeCandidate(BaseModel):

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: int | None = None
    name: str
    categories: tuple[MenuCategory, ...]
    main_ingredients: tuple[str, ...] = ()


    ingredients: tuple[str, ...] = ()
    ingredients_complete: bool = True
    source_type: Literal["canonical_database", "local_json", "wikibooks"]
    source_title: str
    safety_status: Literal["eligible", "unknown"] = "eligible"
