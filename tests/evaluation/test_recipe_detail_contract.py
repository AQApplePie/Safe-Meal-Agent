"""Regression tests for exact recipe targets and requested detail fields."""

from __future__ import annotations

import pytest

from safemeal.modules.recipe.contracts.catalog import (
    RecipeQuery,
    RecipeSearchResult,
)
from safemeal.modules.recipe.contracts.lookup import (
    RecipeCandidate,
    RecipeLookupResult,
)
from safemeal.agent.understanding.request_understanding import (
    RequestUnderstandingService,
)
from safemeal.modules.recipe.application.recipe_service import RecipeService


@pytest.mark.parametrize(
    ("message", "target", "fields"),
    [
        ("水煮鱼有什么材料？", "水煮鱼", ("ingredients",)),
        ("水煮鱼怎么做？", "水煮鱼", ("steps",)),
        ("水煮鱼多久能做好", "水煮鱼", ("time",)),
        ("水煮鱼材料和步骤", "水煮鱼", ("ingredients", "steps")),
        ("告诉我柠檬蒸三文鱼的做法", "柠檬蒸三文鱼", ("steps",)),
        ("麻烦告诉我柠檬蒸三文鱼怎么做", "柠檬蒸三文鱼", ("steps",)),
        (
            "我想知道柠檬蒸三文鱼的材料和具体步骤",
            "柠檬蒸三文鱼",
            ("ingredients", "steps"),
        ),
    ],
)
def test_detail_target_and_fields_are_structured(message, target, fields):
    frame = RequestUnderstandingService().understand(message)

    assert frame.primary_task == "recipe_detail"
    assert frame.target.recipe_name == target
    assert frame.requested_fields == fields
    assert frame.exact_match_required is True


class EmptyRepository:
    def search(self, query: RecipeQuery) -> RecipeSearchResult:
        return RecipeSearchResult(
            items=(), total=0, offset=query.offset, limit=query.limit
        )

    def get(self, recipe_id: int):
        return None


class MissingStepsProvider:
    name = "missing_steps"

    def lookup(self, recipe_name: str) -> RecipeLookupResult:
        return RecipeLookupResult(
            status="FOUND",
            query=recipe_name,
            provider=self.name,
            match_type="exact",
            items=(
                RecipeCandidate(
                    name=recipe_name,
                    ingredients=({"name": "三文鱼", "amount": "200g", "section": "主料"},),
                    steps="",
                    source_type="local_json",
                    source_title="fixture",
                    confidence=1.0,
                    ingredients_complete=True,
                ),
            ),
        )


def test_recipe_found_but_steps_missing_is_not_not_found_or_ingredients_fallback():
    result = RecipeService(
        EmptyRepository(), lookup_providers=(MissingStepsProvider(),)
    ).search(
        RecipeQuery(
            name_contains="柠檬蒸三文鱼",
            exact_name=True,
            required_fields=("steps",),
            limit=1,
        )
    )

    assert result.status == "FIELD_MISSING"
    assert result.missing_fields == ("steps",)
    assert result.items[0].ingredients
    assert result.items[0].steps == ""
