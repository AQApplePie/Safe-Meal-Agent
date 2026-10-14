import pytest

from safemeal.agent.runtime.orchestration.nodes.planner.menu_planning import (
    build_menu_search_plan,
)
from safemeal.agent.contracts.menu_planning import (
    MenuExecutionPlan,
    MenuTaskProgress,
)
from safemeal.agent.understanding.request_understanding import (
    RequestUnderstandingService,
)
from safemeal.agent.context.menu_planning import (
    resolve_active_menu_recipe_reference,
)
from safemeal.agent.contracts.workflow.models import WorkflowRequest
from safemeal.agent.contracts.context import AgentContext
from safemeal.agent.workflow.nodes.prepare_context import PrepareContextNode


def test_replace_category_is_a_modification_not_a_new_recommendation():
    frame = RequestUnderstandingService().understand("重新推荐荤菜")

    assert frame.context_relation == "modification"
    assert frame.operation == "replace"
    assert frame.target.menu_category == "meat"
    assert frame.primary_task == "replace"


def test_category_replacement_search_excludes_previous_selection():
    plan = MenuExecutionPlan(required={"meat": 5})
    progress = MenuTaskProgress(
        fulfilled={"meat": 0},
        remaining={"meat": 5},
        excluded_recipe_ids=(1, 2),
        excluded_recipe_names=("旧菜一", "旧菜二"),
    )

    call = build_menu_search_plan(
        plan.model_dump(mode="json"), progress.model_dump(mode="json")
    )[0]

    assert call.arguments["category"] == "meat"
    assert call.arguments["exclude_recipe_ids"] == [1, 2]
    assert call.arguments["exclude_recipe_names"] == ["旧菜一", "旧菜二"]
    assert "至少 5 道" in call.success_criteria


def test_generic_modification_variants_keep_category_and_explicit_count():
    service = RequestUnderstandingService()
    assert service.understand("汤换一个").target.menu_category == "soup"
    changed = service.understand("荤菜改成三道")
    assert changed.target.menu_category == "meat"
    assert changed.recommendation_count == 3


def test_replacement_target_is_bound_to_replacement_clause():
    frame = RequestUnderstandingService().understand("素菜保留，荤菜重新推荐")

    assert frame.target.menu_category == "meat"


def test_replacement_clause_can_inherit_nearest_previous_category():
    frame = RequestUnderstandingService().understand("荤菜不要鸡肉，重新推荐")

    assert frame.context_relation == "modification"
    assert frame.operation == "replace"
    assert frame.target.menu_category == "meat"


def test_category_ordinal_resolves_from_structured_active_menu():
    active_menu = {
        "progress": {
            "selected_recipes": [
                {"name": "凉拌豆腐", "assigned_category": "cold_dish"},
                {"name": "红烧肉", "assigned_category": "meat"},
                {"name": "清蒸鱼", "assigned_category": "meat"},
            ]
        }
    }

    assert (
        resolve_active_menu_recipe_reference("第二道荤菜怎么做？", active_menu)
        == "清蒸鱼"
    )


@pytest.mark.asyncio
async def test_replacement_excludes_preserved_categories_from_new_candidates():
    active_menu = {
        "plan": {"scenario": "宴席", "required": {"meat": 2, "hot_dish": 1}},
        "progress": {
            "selected_recipes": [
                {"recipe_id": 1, "name": "旧荤菜一", "assigned_category": "meat"},
                {"recipe_id": 2, "name": "旧荤菜二", "assigned_category": "meat"},
                {"recipe_id": 9, "name": "保留热菜", "assigned_category": "hot_dish"},
            ]
        },
    }

    class Builder:
        def build_chat_context(self, **kwargs):
            return AgentContext(
                request_frame=kwargs["request_frame"],
                context_metadata={"active_menu": active_menu},
            )

    update = await PrepareContextNode(Builder())(
        {
            "request": WorkflowRequest(
                message="重新推荐荤菜", user_id="u", session_id="s"
            ),
            "request_frame": RequestUnderstandingService().understand("重新推荐荤菜"),
        }
    )

    modification = update["context"].context_metadata["menu_modification"]
    assert modification["exclude_recipe_ids"] == [1, 2, 9]
    assert modification["replaced_recipe_ids"] == [1, 2]
