"""Application port for the authoritative structured recipe read model."""

from __future__ import annotations

from typing import Protocol

from safemeal.application.contracts.recipes.catalog import (
    RecipeQuery,
    RecipeSearchResult,
)
from safemeal.modules.recipe_catalog.recipe_models import Recipe


class RecipeRepository(Protocol):
    def search(self, query: RecipeQuery) -> RecipeSearchResult: ...

    def get(self, recipe_id: int) -> Recipe | None: ...


__all__ = ["RecipeRepository"]
