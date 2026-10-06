"""定义应用层依赖的能力端口。"""

from typing import Protocol

from safemeal.application.contracts.recipes.lookup import RecipeLookupResult


class RecipeProvider(Protocol):
    name: str

    def lookup(self, recipe_name: str) -> RecipeLookupResult: ...
