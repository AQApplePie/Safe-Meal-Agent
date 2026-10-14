"""Production regressions discovered by authenticated real-provider evaluation."""

import pytest

from safemeal.agent.understanding.request_understanding import (
    RequestUnderstandingService,
)
from safemeal.agent.context.short_term_reference import resolve_recipe_reference
from safemeal.modules.dietary.application.constraints import extract_dietary_constraint


def test_rendered_detail_heading_is_a_trusted_recent_reference():
    history = [
        dict(role="assistant", content="清蒸鲈鱼的材料：\n- 鲈鱼：100g\n- 盐：1g")
    ]
    assert resolve_recipe_reference("这个怎么做？", history) == ("清蒸鲈鱼", None)
    assert (
        RequestUnderstandingService()
        .understand("这个怎么做？", history)
        .target.recipe_name
        == "清蒸鲈鱼"
    )


def test_negative_modifier_does_not_exclude_requested_food_category():
    message = "推荐两道不含花生的鱼"
    constraint = extract_dietary_constraint(message)
    assert "花生" in constraint.raw_ingredients
    assert "鱼" not in constraint.raw_ingredients
    frame = RequestUnderstandingService().understand(message)
    assert any(
        c.kind == "food_category" and c.value == "fish"
        for c in frame.current_constraints
    )
    assert not any(m.value == "鱼" for m in frame.memory_updates)
    assert (
        "鱼"
        in extract_dietary_constraint("我对鱼过敏，推荐不含花生的鱼").raw_ingredients
    )


def test_partial_menu_replacement_preserves_other_slot_in_same_category():
    from safemeal.agent.context.active_menu import merge_active_menu_replacement

    def item(name, category):
        return dict(
            name=name,
            assigned_category=category,
            categories=[category],
            evidence_call_id="previous",
        )

    previous = dict(
        plan=dict(required=dict(meat=1, vegetarian=2)),
        progress=dict(
            fulfilled=dict(meat=1, vegetarian=2),
            remaining=dict(meat=0, vegetarian=0),
            selected_recipes=[
                item("鱼", "meat"),
                item("青菜", "vegetarian"),
                item("黄瓜", "vegetarian"),
            ],
        ),
    )
    replacement = dict(
        fulfilled=dict(vegetarian=1),
        remaining=dict(vegetarian=0),
        selected_recipes=[item("豆腐", "vegetarian")],
    )
    merged = merge_active_menu_replacement(
        previous,
        dict(required=dict(vegetarian=1)),
        replacement,
        dict(
            target_category="vegetarian", partial=True, replaced_recipe_names=["青菜"]
        ),
    )
    assert merged["plan"]["required"] == dict(meat=1, vegetarian=2)
    assert {r["name"] for r in merged["progress"]["selected_recipes"]} == {
        "鱼",
        "黄瓜",
        "豆腐",
    }
    assert merged["progress"]["complete"]


@pytest.mark.asyncio
async def test_retained_menu_recipe_is_rechecked_under_new_allergy():
    from safemeal.agent.workflow.nodes.safety import check_final_safety
    from safemeal.agent.contracts.api import AgentProcessResponse
    from safemeal.agent.contracts.intent import IntentDecision
    from safemeal.agent.contracts.context import AgentContext
    from safemeal.agent.safety.dietary_safety_service import DietarySafetyService

    def item(name, category):
        return dict(
            name=name,
            assigned_category=category,
            categories=[category],
            evidence_call_id="previous",
        )

    active = dict(
        plan=dict(required=dict(meat=1, vegetarian=1)),
        progress=dict(
            fulfilled=dict(meat=1, vegetarian=1),
            remaining=dict(meat=0, vegetarian=0),
            selected_recipes=[item("清蒸鱼", "meat"), item("花生拌黄瓜", "vegetarian")],
            candidate_pool=[
                dict(name="清蒸鱼", ingredients=["鱼"], ingredients_complete=True),
                dict(
                    name="花生拌黄瓜",
                    ingredients=["花生", "黄瓜"],
                    ingredients_complete=True,
                ),
            ],
        ),
    )
    result = AgentProcessResponse(
        message="草稿",
        intent=IntentDecision(kind="menu_planning", reason="test"),
        metadata=dict(active_menu=active, menu_modification=dict(partial=True)),
    )
    state = dict(
        result=result,
        requirements=DietarySafetyService().resolve_constraints(
            "我花生过敏", AgentContext()
        ),
    )
    reviewed = (await check_final_safety(state))["result"]
    assert "花生拌黄瓜" not in reviewed.metadata["safe_recipe_names"]
    assert "花生拌黄瓜" not in reviewed.message
    assert not reviewed.metadata["post_safety_coverage"]["complete"]
    assert reviewed.status == "degraded"
