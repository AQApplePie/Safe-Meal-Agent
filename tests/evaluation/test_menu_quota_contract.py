"""Regression cases for coordinated menu quota understanding."""

import pytest

from safemeal.agent.understanding.request_understanding import (
    RequestUnderstandingService,
)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("给四个人安排两道荤菜", {"meat": 2}),
        ("给四个人安排两荤两素", {"meat": 2, "vegetarian": 2}),
        (
            "给四个人安排两荤两素一汤",
            {"meat": 2, "vegetarian": 2, "soup": 1},
        ),
        (
            "农村宴席，三凉三热三素三荤三汤三主食",
            {
                "cold_dish": 3,
                "hot_dish": 3,
                "vegetarian": 3,
                "meat": 3,
                "soup": 3,
                "staple": 3,
            },
        ),
    ],
)
def test_coordinated_menu_structure_produces_exact_quotas(message, expected):
    frame = RequestUnderstandingService().understand(message)

    assert frame.primary_task == "menu_planning"
    assert frame.menu_planning is not None
    assert {
        item.category: item.count for item in frame.menu_planning.category_quotas
    } == expected
    assert frame.recommendation_count == sum(expected.values())
    assert frame.menu_planning.distinct_recipes is True
    assert frame.menu_planning.allow_cross_category_counting is False


def test_people_count_is_servings_while_menu_slots_come_from_quotas():
    frame = RequestUnderstandingService().understand(
        "给四个人安排两荤两素一汤"
    )

    assert frame.servings == 4
    assert frame.recommendation_count == 5


def test_servings_is_not_recipe_count_for_a_plain_meal_recommendation():
    frame = RequestUnderstandingService().understand("给四个人推荐午餐")

    assert frame.primary_task == "recipe_recommendation"
    assert frame.servings == 4
    assert frame.recommendation_count is None


def test_explicit_dish_count_is_not_servings():
    frame = RequestUnderstandingService().understand("推荐四道菜")

    assert frame.primary_task == "recipe_recommendation"
    assert frame.recommendation_count == 4
    assert frame.servings is None


def test_large_single_category_count_remains_a_recommendation():
    frame = RequestUnderstandingService().understand("推荐十道鱼")

    assert frame.primary_task == "recipe_recommendation"
    assert frame.recommendation_count == 10
    assert frame.menu_planning is None
    assert [(item.kind, item.value) for item in frame.current_constraints] == [
        ("food_category", "fish")
    ]


def test_coordinated_structure_not_large_number_defines_menu_planning():
    frame = RequestUnderstandingService().understand("两荤两素一汤")

    assert frame.primary_task == "menu_planning"
    assert frame.recommendation_count == 5
