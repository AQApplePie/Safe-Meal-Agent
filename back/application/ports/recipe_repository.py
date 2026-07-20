"""Application port for the authoritative structured recipe read model."""

from __future__ import annotations

from typing import Protocol

from SafeMealAgent.back.application.domain.recipes import Recipe, RecipeQuery, RecipeSearchResult


class RecipeRepository(Protocol):
    def search(self, query: RecipeQuery) -> RecipeSearchResult: ...

    def get(self, recipe_id: int) -> Recipe | None: ...


__all__ = ["RecipeRepository"]
