"""Read-only provider boundary for non-canonical recipe sources."""

from typing import Protocol

from safemeal.application.contracts.recipes.lookup import RecipeLookupResult


class RecipeProvider(Protocol):
    name: str

    def lookup(self, recipe_name: str) -> RecipeLookupResult: ...
