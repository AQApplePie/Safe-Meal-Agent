"""Infrastructure-independent capabilities required by Agent tools."""

from typing import Protocol
from safemeal.application.contracts.tools.payloads import DietarySafeRecipeQueryResult


class DietarySearch(Protocol):
    def search(
        self,
        *,
        excluded_ingredients: list[str],
        target_dish: str | None,
        recommend_limit: int,
        excluded_limit: int,
    ) -> DietarySafeRecipeQueryResult: ...
