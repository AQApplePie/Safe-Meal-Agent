import pytest
from safemeal.agent.runtime.tools.policy import review_tool_calls
from safemeal.agent.contracts.decisions import ToolCall, Observation
from safemeal.modules.dietary.contracts.constraints import DietaryConstraint
from safemeal.modules.dietary.application.constraints import (
    build_dietary_safety_result,
)
from safemeal.modules.dietary.application.generated_safety import (
    generated_recipe_violations,
)
from safemeal.modules.recipe.contracts.generated import GeneratedRecipe


def call(name, args):
    return ToolCall(
        id="1", tool_name=name, arguments=args, purpose="test", success_criteria="safe"
    )


@pytest.mark.parametrize(
    "name,key",
    [
        ("search_recipes", "exclude_ingredients"),
        ("recommend_recipes", "exclude_ingredients"),
        ("generate_recipe", "exclude_ingredients"),
        ("dietary_safe_recipe_query", "excluded_ingredients"),
    ],
)
def test_all_recipe_queries_receive_non_overridable_exclusions(name, key):
    accepted, rejected = review_tool_calls(
        [call(name, {key: ["鸡蛋"]})], {"excluded_ingredients": ["花生"]}
    )
    assert not rejected
    assert accepted[0].arguments[key] == ["鸡蛋", "花生"]


def test_later_conflicting_recipe_cannot_be_hidden_by_name_deduplication():
    obs = [
        Observation(
            call_id="c",
            tool_name="recommend_recipes",
            purpose="test",
            success_criteria="safe",
            ok=True,
            has_data=True,
            summary="",
            data={
                "items": [
                    {"name": "菜", "ingredients": ["土豆"]},
                    {"name": "菜", "ingredients": ["花生"]},
                ]
            },
        )
    ]
    result = build_dietary_safety_result(
        constraint=DietaryConstraint(active=True, excluded_ingredients=["花生"]),
        observations=obs,
    )
    assert not result.safe_recipes
    assert len(result.excluded_recipes) == 1


@pytest.mark.parametrize(
    "row",
    [
        {"name": "菜", "ingredients": ["土豆"], "ingredients_complete": False},
        {"name": "菜", "ingredients": ["土豆"], "safety_status": "unknown"},
    ],
)
def test_incomplete_ingredient_evidence_stays_unknown(row):
    obs = [
        Observation(
            call_id="c",
            tool_name="recommend_recipes",
            purpose="test",
            success_criteria="safe",
            ok=True,
            has_data=True,
            summary="",
            data={"items": [row]},
        )
    ]
    result = build_dietary_safety_result(
        constraint=DietaryConstraint(active=True, excluded_ingredients=["花生"]),
        observations=obs,
    )
    assert not result.safe_recipes
    assert len(result.unknown_recipes) == 1


@pytest.mark.parametrize(
    "step,unsafe",
    [("加入花生搅拌", True), ("不要加入花生", False), ("加入花生，不要加鸡蛋", True)],
)
def test_generated_steps_distinguish_prohibition_from_use(step, unsafe):
    recipe = GeneratedRecipe(
        name="菜",
        description="蒸菜",
        total_time_minutes=10,
        servings=1,
        difficulty="easy",
        ingredients=[{"name": "土豆", "quantity": 100, "unit": "g"}],
        steps=[{"number": 1, "action": "蒸", "instruction": step}],
        nutrition={},
    )
    assert bool(generated_recipe_violations(recipe, ["花生"])) is unsafe
