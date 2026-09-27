"""Infrastructure-independent capabilities required by Agent tools."""

from typing import Protocol
from safemeal.application.contracts.tools.payloads import DietarySafeRecipeQueryResult
from safemeal.shared.types import JsonObject


class DietarySearch(Protocol):
    def search(
        self,
        *,
        excluded_ingredients: list[str],
        target_dish: str | None,
        recommend_limit: int,
        excluded_limit: int,
    ) -> DietarySafeRecipeQueryResult: ...


class McpGateway(Protocol):
    async def list_tools(self) -> list[JsonObject]: ...
    async def call_tool(
        self, server_name: str, tool_name: str, arguments: JsonObject
    ) -> JsonObject: ...
