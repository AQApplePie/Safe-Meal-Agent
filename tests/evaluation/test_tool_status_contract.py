"""Failure-state regression suite for recipe Tool contracts."""

import pytest

from safemeal.agent.runtime.tools.runtime import LocalToolExecutor
from safemeal.agent.contracts.decisions import ToolCall
from safemeal.modules.recipe.contracts.catalog import (
    RecipeQuery,
    RecipeSearchResult,
)
from safemeal.modules.recipe.contracts.lookup import RecipeLookupResult
from safemeal.shared.exceptions import DatabaseUnavailableError
from safemeal.modules.recipe.application.recipe_service import RecipeService
from safemeal.agent.runtime.tools.adapters.recipe_tools import SearchRecipesTool


class EmptyRepository:
    def search(self, query: RecipeQuery) -> RecipeSearchResult:
        return RecipeSearchResult(
            items=(), total=0, offset=query.offset, limit=query.limit
        )

    def get(self, recipe_id: int):
        return None


class ErrorProvider:
    name = "external_error"

    def lookup(self, recipe_name: str) -> RecipeLookupResult:
        return RecipeLookupResult(
            status="ERROR",
            query=recipe_name,
            provider=self.name,
            error="upstream unavailable",
        )


class UnavailableRepository(EmptyRepository):
    def search(self, query: RecipeQuery) -> RecipeSearchResult:
        raise DatabaseUnavailableError()


def test_empty_successful_lookup_is_not_found():
    result = RecipeService(EmptyRepository()).search(
        RecipeQuery(name_contains="不存在的菜", exact_name=True, limit=1)
    )

    assert result.status == "NOT_FOUND"
    assert result.errors == ()


def test_external_failure_is_error_not_not_found():
    result = RecipeService(
        EmptyRepository(), lookup_providers=(ErrorProvider(),)
    ).search(RecipeQuery(name_contains="外部菜", exact_name=True, limit=1))

    assert result.status == "ERROR"
    assert result.errors == ("external_error: upstream unavailable",)


@pytest.mark.asyncio
async def test_database_timeout_becomes_unavailable_tool_result():
    executor = LocalToolExecutor(
        [SearchRecipesTool(RecipeService(UnavailableRepository()))]
    )

    result = await executor.invoke(
        ToolCall(
            id="db-timeout",
            tool_name="search_recipes",
            arguments={"name_contains": "水煮鱼", "exact_name": True, "limit": 1},
            purpose="lookup",
            success_criteria="found or explicit error",
        )
    )

    assert result.ok is False
    assert result.status == "unavailable"
    assert result.error_code == "database_unavailable"
    assert result.retryable is True
