from pathlib import Path

import pytest

from safemeal.agent.gateway import AgentExecutionService
from safemeal.agent.runtime.orchestration import build_agent_graph
from safemeal.agent.runtime.aggregation.recipe_detail import (
    render_exact_recipe_detail,
)
from safemeal.agent.runtime.aggregation.recommendation import (
    render_recipe_recommendations,
)
from safemeal.agent.runtime.tools.runtime import LocalToolExecutor
from safemeal.agent.contracts.context import AgentContext
from safemeal.agent.contracts.decisions import Observation
from safemeal.agent.contracts.workflow.models import WorkflowRequest
from safemeal.modules.dietary.contracts.requirements import (
    DietaryPreference,
    DietaryRequirements,
)
from safemeal.agent.safety.dietary_safety_service import (
    DietarySafetyService,
)
from safemeal.modules.dietary.application.food_taxonomy import (
    ingredient_belongs_to_category,
)
from safemeal.agent.understanding.request_understanding import (
    RequestUnderstandingService,
)
from safemeal.modules.recipe.contracts.catalog import RecipeSearchResult
from safemeal.modules.recipe.application.recipe_service import RecipeService
from safemeal.agent.runtime.tools.adapters.recipe_tools import SearchRecipesTool
from safemeal.agent.workflow.context.builder import AgentContextBuilder
from safemeal.agent.workflow.graph import build_chat_workflow
from safemeal.agent.workflow.runner import ChatWorkflow
from safemeal.infrastructure.retrieval.local_recipe_catalog import (
    LocalRecipeDocumentCatalog,
)


ROOT = Path(__file__).resolve().parents[2]


def test_exact_recipe_detail_renders_only_requested_steps():
    answer = render_exact_recipe_detail(
        {
            "name": "柠檬蒸三文鱼",
            "ingredients": [{"name": "三文鱼", "amount": "280g"}],
            "steps": "腌制10分钟。\n水开后大火蒸8分钟。\n挤入柠檬汁。",
        },
        ("steps",),
    )

    assert "柠檬蒸三文鱼的做法" in answer
    assert "1. 腌制10分钟" in answer
    assert "3. 挤入柠檬汁" in answer
    assert "材料" not in answer


def test_exact_recipe_detail_reports_missing_requested_field_without_substitution():
    answer = render_exact_recipe_detail(
        {"name": "只有材料的菜", "ingredients": [{"name": "鱼"}]},
        ("steps",),
    )

    assert answer == "只有材料的菜：当前来源没有提供具体做法。"
    assert "适量" not in answer


def test_exact_recipe_detail_can_render_multiple_explicit_fields():
    answer = render_exact_recipe_detail(
        {
            "name": "测试菜",
            "ingredients": [{"name": "鱼", "amount": "200g"}],
            "steps": "蒸熟。",
            "nutrition": {
                "calories": 420,
                "protein_g": 38,
                "basis": "per_recipe",
            },
        },
        ("ingredients", "steps", "nutrition"),
    )

    assert "测试菜的材料" in answer
    assert "测试菜的做法" in answer
    assert "热量：420kcal" in answer
    assert "计算基准：整份" in answer


def test_recommendation_renderer_never_exposes_boolean_recipe_metadata():
    answer = render_recipe_recommendations(
        [
            Observation(
                call_id="recommend",
                tool_name="recommend_recipes",
                purpose="recommend",
                success_criteria="candidates",
                ok=True,
                has_data=True,
                summary="recipes",
                data={
                    "items": [
                        {
                            "name": "豆芽水煮鱼片",
                            "ingredients": [
                                {"ingredient": {"name": "草鱼"}, "is_main": True},
                                {"name": "豆芽"},
                            ],
                            "ingredients_complete": True,
                        }
                    ]
                },
            )
        ]
    )

    assert answer is not None
    assert "草鱼、豆芽" in answer
    assert "True" not in answer


def _observation(rows):
    return Observation(
        call_id="recommend",
        tool_name="recommend_recipes",
        purpose="recommend",
        success_criteria="complete ingredients",
        ok=True,
        has_data=True,
        summary="recipes",
        data={"items": rows},
    )


def test_preference_and_exact_recipe_detail_are_independent():
    frame = RequestUnderstandingService().understand("我爱吃鱼，水煮鱼的材料是什么")
    assert frame.primary_task == "recipe_detail"
    assert frame.target.recipe_name == "水煮鱼"
    assert frame.requested_fields == ("ingredients",)
    assert frame.memory_updates[0].value == "鱼"
    result = LocalRecipeDocumentCatalog(ROOT / "data/recipe.json").lookup("水煮鱼")
    assert result.status == "FOUND" and result.match_type == "exact"
    assert result.items[0].name == "水煮鱼"
    assert {item["name"] for item in result.items[0].ingredients} >= {"草鱼", "金针菇"}


def test_allergy_statement_keeps_same_turn_recommendation_task():
    frame = RequestUnderstandingService().understand(
        "我对花生过敏，有没有什么没有花生的菜"
    )
    assert frame.primary_task == "recipe_recommendation"
    assert [(item.kind, item.value) for item in frame.memory_updates] == [
        ("allergy", "花生")
    ]
    assert [(item.kind, item.value) for item in frame.current_constraints] == [
        ("allergy", "花生")
    ]


def test_fish_preference_ranks_fish_and_peanut_is_hard_excluded():
    requirements = DietaryRequirements(
        allergies=DietarySafetyService()
        .resolve_constraints(
            "",
            [],
            AgentContext(
                user_memories=[
                    {
                        "memory_type": "dietary_allergy",
                        "memory_key": "花生",
                        "memory_value": "花生过敏",
                    }
                ]
            ),
        )
        .allergies,
        preferences=[
            DietaryPreference(kind="include_ingredient", value="鱼", source="memory")
        ],
    )
    review = DietarySafetyService().review_recipes(
        requirements,
        [
            _observation(
                [
                    {"name": "花生鲈鱼", "ingredients": ["鲈鱼", "花生"]},
                    {"name": "清蒸鲈鱼", "ingredients": ["鲈鱼", "姜"]},
                    {"name": "三文鱼沙拉", "ingredients": ["三文鱼", "生菜"]},
                    {"name": "虾仁炒蛋", "ingredients": ["虾仁", "鸡蛋"]},
                    {"name": "炒青菜", "ingredients": ["青菜"]},
                ]
            )
        ],
    )
    assert review.recipes[0].name == "清蒸鲈鱼"
    assert review.recipes[1].name == "三文鱼沙拉"
    assert (
        next(item for item in review.recipes if item.name == "花生鲈鱼").decision
        == "excluded"
    )
    assert ingredient_belongs_to_category("虾仁", "鱼") is False


class _ModelThatMustNotPlan:
    async def plan(self, **kwargs):
        raise AssertionError("exact lookup must bypass model planning")

    async def reflect(self, **kwargs):
        raise AssertionError("terminal lookup status must bypass model reflection")

    async def answer(self, **kwargs):
        raise AssertionError("exact lookup has a deterministic renderer")


class _EmptyRepository:
    def search(self, query):
        return RecipeSearchResult(
            items=(), total=0, offset=query.offset, limit=query.limit
        )

    def get(self, recipe_id):
        return None


@pytest.mark.asyncio
async def test_exact_lookup_converges_after_one_tool_call_and_not_found_is_stable(
    tmp_path,
):
    catalog_path = tmp_path / "recipes.json"
    catalog_path.write_text("{}", encoding="utf-8")
    service = RecipeService(
        _EmptyRepository(),
        lookup_providers=(LocalRecipeDocumentCatalog(catalog_path),),
    )
    executor = LocalToolExecutor([SearchRecipesTool(service)])
    agent = AgentExecutionService(
        build_agent_graph(model_gateway=_ModelThatMustNotPlan(), tool_executor=executor)
    )
    frame = RequestUnderstandingService().understand("不存在的菜的材料是什么")
    response = await agent.process(
        "不存在的菜的材料是什么",
        "not-found",
        context=AgentContext(request_frame=frame),
    )
    assert response.status == "ok"
    assert "未在可用食谱来源中找到" in response.message
    exact = [
        item for item in response.evidence if item["tool_name"] == "search_recipes"
    ]
    assert len(exact) == 1
    assert exact[0]["data"]["status"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_full_workflow_saves_preference_without_overwriting_recipe_answer():
    class Memory:
        saved = []

        def load_agent_memories(self, **kwargs):
            return []

        def load_episodic_memories(self, **kwargs):
            return []

        def remember_from_message(self, **kwargs):
            self.saved.append(kwargs["message"])
            return [{"memory_key": "鱼"}]

    memory = Memory()
    service = RecipeService(
        _EmptyRepository(),
        lookup_providers=(LocalRecipeDocumentCatalog(ROOT / "data/recipe.json"),),
    )
    executor = LocalToolExecutor([SearchRecipesTool(service)])
    agent = AgentExecutionService(
        build_agent_graph(model_gateway=_ModelThatMustNotPlan(), tool_executor=executor)
    )
    workflow = ChatWorkflow(
        build_chat_workflow(
            agent=agent,
            context_builder=AgentContextBuilder(),
            memory_service=memory,
        )
    )
    response = await workflow.run(
        WorkflowRequest(
            message="我爱吃鱼，水煮鱼的材料是什么",
            user_id="u",
            session_id="full-path",
        )
    )
    assert response.intent.kind == "recipe_detail"
    assert "草鱼" in response.message and "金针菇" in response.message
    assert "已保存" not in response.message
    assert memory.saved == ["我爱吃鱼，水煮鱼的材料是什么"]
    assert response.metadata["memory_saved"] is True


def test_dislike_memory_and_recommendation_are_both_preserved():
    frame = RequestUnderstandingService().understand("我不喜欢香菜，推荐几个牛肉菜")
    assert frame.primary_task == "recipe_recommendation"
    assert [(item.kind, item.value) for item in frame.memory_updates] == [
        ("dislike", "香菜")
    ]


def test_graph_node_budgets_are_unchanged_for_agent_and_one_added_for_workflow():
    class _Tools:
        def specifications(self):
            return []

    from safemeal.agent.workflow.graph import build_chat_workflow
    from safemeal.agent.workflow.context.builder import AgentContextBuilder

    class _Memory:
        def load_agent_memories(self, **kwargs):
            return []

        def load_episodic_memories(self, **kwargs):
            return []

    agent_graph = build_agent_graph(
        model_gateway=_ModelThatMustNotPlan(), tool_executor=_Tools()
    )
    workflow_graph = build_chat_workflow(
        agent=object(), context_builder=AgentContextBuilder(), memory_service=_Memory()
    )
    assert len(agent_graph.get_graph().nodes) - 2 == 7
    assert len(workflow_graph.get_graph().nodes) - 2 == 6
