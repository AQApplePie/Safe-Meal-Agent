"""定义应用层依赖的能力端口。"""

from __future__ import annotations

from typing import Protocol

from safemeal.modules.recipe.contracts.catalog import (
    RecipeQuery,
    RecipeSearchResult,
)
from safemeal.modules.recipe.contracts.models import Recipe


class RecipeRepository(Protocol):
    def search(self, query: RecipeQuery) -> RecipeSearchResult: ...

    def get(self, recipe_id: int) -> Recipe | None: ...


__all__ = ["RecipeRepository"]
