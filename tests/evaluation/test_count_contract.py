"""Regression contract for explicit recommendation quantities."""

from __future__ import annotations

from decimal import Decimal

import pytest

from safemeal.application.agent.orchestration.nodes.planner.node import (
    create_planner_node,
)
from safemeal.application.contracts.agent.context import AgentContext
from safemeal.application.contracts.recipes.catalog import (
    RecipeQuery,
    RecipeSearchResult,
)
from safemeal.application.contracts.recipes.models import (
    CookingStep,
    Ingredient,
    IngredientQuantity,
    NutritionInfo,
    Recipe,
    RecipeDifficulty,
)
from safemeal.application.contracts.tools.base import ToolSpecification
from safemeal.application.contracts.workflow.request_frame import (
    CurrentConstraint,
    RequestFrame,
    RequestTask,
)
from safemeal.application.service.chat.request_understanding import (
    RequestUnderstandingService,
)
from safemeal.application.service.recipes.recipe_service import RecipeService


def _recipe(
    index: int, *, ingredient_name: str | None = None, name: str | None = None
) -> Recipe:
    nutrition = NutritionInfo()
    return Recipe(
        id=index,
        name=name or f"家常菜{index}",
        total_time_minutes=10,
        servings=1,
        difficulty=RecipeDifficulty.EASY,
        ingredients=(
            IngredientQuantity(
                ingredient=Ingredient(
                    id=index,
                    name=ingredient_name or f"食材{index}",
                    nutrition=nutrition,
                ),
                quantity=Decimal("1"),
                unit="g",
                preparation=None,
                is_main=True,
                ingredient_type="main",
            ),
        ),
        steps=(CookingStep(number=1, action="烹饪", instruction="制作完成。"),),
        nutrition=nutrition,
    )


class PagingRepository:
    def __init__(self, count: int = 0, *, items: tuple[Recipe, ...] = ()):
        self.items = items or tuple(_recipe(index) for index in range(1, count + 1))

    def search(self, query: RecipeQuery) -> RecipeSearchResult:
        items = self.items[query.offset : query.offset + query.limit]
        return RecipeSearchResult(
            items=items,
            total=len(self.items),
            offset=query.offset,
            limit=query.limit,
        )

    def get(self, recipe_id: int):
        return None


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("推荐一道鱼", 1),
        ("推荐两道鱼", 2),
        ("推荐四道鱼", 4),
        ("推荐六道家常菜", 6),
    ],
)
def test_explicit_count_survives_request_frame(message: str, expected: int):
    frame = RequestUnderstandingService().understand(message)

    assert frame.primary_task == "recipe_recommendation"
    assert frame.recommendation_count == expected


class NoModelPlanning:
    async def plan(self, **kwargs):
        raise AssertionError("an explicit count must not be re-extracted by the LLM")


class RecommendationTool:
    def specifications(self):
        return [
            ToolSpecification(
                name="recommend_recipes",
                description="recommend",
                arguments_schema={"type": "object"},
            )
        ]


@pytest.mark.asyncio
async def test_planner_propagates_requested_count_and_oversamples_candidates():
    frame = RequestFrame(
        tasks=(RequestTask(kind="recipe_recommendation"),),
        recommendation_count=4,
    )
    planner = create_planner_node(NoModelPlanning(), RecommendationTool())

    output = await planner(
        {
            "question": "推荐四道鱼",
            "agent_context": AgentContext(request_frame=frame).model_dump(mode="json"),
            "observations": [],
        }
    )

    arguments = output["pending_calls"][0].arguments
    assert arguments["requested_count"] == 4
    assert arguments["candidate_limit"] == 12
    assert arguments["limit"] == 12


@pytest.mark.asyncio
async def test_planner_scans_bounded_catalog_for_post_query_food_category():
    frame = RequestFrame(
        tasks=(RequestTask(kind="recipe_recommendation"),),
        recommendation_count=4,
        current_constraints=(CurrentConstraint(kind="food_category", value="fish"),),
    )
    planner = create_planner_node(NoModelPlanning(), RecommendationTool())

    output = await planner(
        {
            "question": "推荐四道鱼",
            "agent_context": AgentContext(request_frame=frame).model_dump(mode="json"),
            "observations": [],
        }
    )

    arguments = output["pending_calls"][0].arguments
    assert arguments["candidate_limit"] == 200
    assert arguments["food_categories"] == ["fish"]


@pytest.mark.parametrize("requested", [1, 2, 4, 6])
def test_recipe_service_returns_exact_requested_count(requested: int):
    result = RecipeService(PagingRepository(10)).recommend(
        RecipeQuery(
            requested_count=requested,
            candidate_limit=min(50, requested * 2 + 2),
            limit=min(50, requested * 2 + 2),
        )
    )

    assert result.status == "FOUND"
    assert result.requested_count == requested
    assert result.fulfilled_count == requested
    assert len(result.items) == requested


def test_recipe_service_reports_partial_instead_of_claiming_completion():
    result = RecipeService(PagingRepository(3)).recommend(
        RecipeQuery(requested_count=4, candidate_limit=8, limit=8)
    )

    assert result.status == "PARTIAL"
    assert result.requested_count == 4
    assert result.fulfilled_count == 3
    assert len(result.items) == 3


def test_current_query_food_category_is_hard_while_a_like_is_not():
    hard = RequestUnderstandingService().understand("推荐四道鱼")
    soft = RequestUnderstandingService().understand("我喜欢吃鱼，给我推荐几道菜")

    assert ("food_category", "fish") in [
        (item.kind, item.value) for item in hard.current_constraints
    ]
    assert not any(item.kind == "food_category" for item in soft.current_constraints)


def test_fish_category_excludes_shrimp_chicken_and_misleading_recipe_names():
    recipes = (
        _recipe(1, ingredient_name="三文鱼", name="香煎三文鱼"),
        _recipe(2, ingredient_name="鲈鱼", name="清蒸鲈鱼"),
        _recipe(3, ingredient_name="鳕鱼", name="香煎鳕鱼"),
        _recipe(4, ingredient_name="草鱼", name="水煮鱼"),
        _recipe(5, ingredient_name="虾仁", name="柠檬蒸虾仁"),
        _recipe(6, ingredient_name="鸡肉", name="姜汁鸡腿"),
        _recipe(7, ingredient_name="猪肉", name="鱼香肉丝"),
    )

    result = RecipeService(PagingRepository(items=recipes)).recommend(
        RecipeQuery(
            food_categories=("fish",),
            requested_count=4,
            candidate_limit=10,
            limit=10,
        )
    )

    assert result.status == "FOUND"
    assert [item.name for item in result.items] == [
        "香煎三文鱼",
        "清蒸鲈鱼",
        "香煎鳕鱼",
        "水煮鱼",
    ]


def test_seafood_category_can_include_fish_and_shrimp():
    recipes = (
        _recipe(1, ingredient_name="三文鱼", name="三文鱼菜"),
        _recipe(2, ingredient_name="虾仁", name="虾仁菜"),
        _recipe(3, ingredient_name="鸡肉", name="鸡肉菜"),
    )

    result = RecipeService(PagingRepository(items=recipes)).recommend(
        RecipeQuery(
            food_categories=("seafood",),
            requested_count=2,
            candidate_limit=6,
            limit=6,
        )
    )

    assert [item.name for item in result.items] == ["三文鱼菜", "虾仁菜"]


def test_vegetarian_category_uses_structured_ingredients():
    recipes = (
        _recipe(1, ingredient_name="嫩豆腐", name="清炒豆腐"),
        _recipe(2, ingredient_name="小白菜", name="清炒小白菜"),
        _recipe(3, ingredient_name="鸡肉", name="鸡肉小炒"),
    )

    result = RecipeService(PagingRepository(items=recipes)).recommend(
        RecipeQuery(
            food_categories=("vegetarian",),
            requested_count=2,
            candidate_limit=6,
            limit=6,
        )
    )

    assert [item.name for item in result.items] == ["清炒豆腐", "清炒小白菜"]
