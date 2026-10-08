"""定义应用层依赖的能力端口。"""

from typing import Protocol
from safemeal.agent.runtime.tools.contracts.payloads import DietarySafeRecipeQueryResult


class DietarySearch(Protocol):
    def search(
        self,
        *,
        excluded_ingredients: list[str],
        target_dish: str | None,
        recommend_limit: int,
        excluded_limit: int,
    ) -> DietarySafeRecipeQueryResult: ...
