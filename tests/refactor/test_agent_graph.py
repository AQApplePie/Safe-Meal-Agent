import pytest
from langgraph.checkpoint.memory import MemorySaver
from safemeal.agent.runtime.orchestration import build_agent_graph
from safemeal.agent.gateway import AgentExecutionService
from safemeal.agent.contracts.context import AgentContext
from safemeal.agent.contracts.decisions import (
    PlanDecision,
    Observation,
    ToolCall,
    ReflectionDecision,
)
from safemeal.agent.runtime.tools.contracts.base import ToolResult, ToolSpecification
from safemeal.agent.workflow.graph import build_resume_workflow
from safemeal.agent.workflow.runner import ChatWorkflow
from safemeal.agent.runtime.orchestration.nodes.planner.menu_planning import (
    build_menu_search_plan,
)
from safemeal.agent.contracts.menu_planning import (
    MenuExecutionPlan,
    MenuTaskProgress,
    SelectedMenuRecipe,
)
from safemeal.agent.runtime.orchestration.nodes.observer.menu_progress import (
    update_menu_task_progress,
)
from safemeal.agent.runtime.orchestration.nodes.reflector.node import (
    create_reflector_node,
)
from safemeal.agent.runtime.orchestration.nodes.planner.intent import (
    intent_from_request_frame,
)
from safemeal.shared.contracts.request_frame import (
    CategoryQuota,
    MenuPlanningRequirements,
    RequestFrame,
    RequestTask,
)
from safemeal.agent.runtime.menu_output import render_menu_plan


class Model:
    def __init__(self, tool="recommend_recipes"):
        self.tool = tool

    async def plan(self, **kwargs):
        return PlanDecision(
            decision="tools",
            rationale="find recipes",
            calls=[
                ToolCall(
                    id="c",
                    tool_name=self.tool,
                    arguments={},
                    purpose="find food",
                    success_criteria="complete ingredients",
                )
            ],
        )

    async def reflect(self, **kwargs):
        return ReflectionDecision(
            decision="finish", rationale="enough", evidence_sufficient=True
        )

    async def answer(self, **kwargs):
        return "推荐蒸土豆"


class Tools:
    def __init__(self, name="recommend_recipes"):
        self.name = name
        self.calls = []

    def specifications(self):
        return [
            ToolSpecification(
                name=self.name, description="test", arguments_schema={"type": "object"}
            )
        ]

    async def invoke_many(self, calls):
        self.calls.extend(calls)
        return [
            ToolResult(
                call_id=c.id,
                tool_name=c.tool_name,
                ok=True,
                data={"items": [{"name": "蒸土豆", "ingredients": ["土豆"]}]},
            )
            for c in calls
        ]


def test_explicit_menu_quotas_use_menu_intent_even_after_nlu_fallback():
    context = AgentContext(
        request_frame=RequestFrame(
            tasks=(RequestTask(kind="menu_planning"),),
            menu_planning=MenuPlanningRequirements(
                category_quotas=(
                    CategoryQuota(category="cold_dish", count=2),
                    CategoryQuota(category="hot_dish", count=2),
                )
            ),
            understanding_status="fallback",
            backend="local_model:rules_fallback",
        )
    )

    intent = intent_from_request_frame(context)

    assert intent is not None
    assert intent.kind == "menu_planning"

def test_menu_planner_batches_remaining_quotas_and_excludes_selected_recipes():
    plan = MenuExecutionPlan(
        scenario="农村宴席",
        required={"cold_dish": 3, "hot_dish": 3, "soup": 3},
    )
    progress = MenuTaskProgress(
        fulfilled={"cold_dish": 2, "hot_dish": 3, "soup": 0},
        remaining={"cold_dish": 1, "hot_dish": 0, "soup": 3},
        selected_recipes=(
            SelectedMenuRecipe(
                recipe_id=7,
                name="凉拌豆腐",
                assigned_category="cold_dish",
                categories=("cold_dish", "vegetarian"),
                evidence_call_id="old",
            ),
        ),
        attempted_categories={"cold_dish": 1, "hot_dish": 1, "soup": 0},
    )

    calls = build_menu_search_plan(
        plan.model_dump(mode="json"), progress.model_dump(mode="json")
    )

    assert [call.arguments["category"] for call in calls] == ["soup", "cold_dish"]
    assert all(call.tool_name == "search_recipes" for call in calls)
    assert calls[0].arguments["limit"] == 6
    assert calls[1].arguments["limit"] == 5
    assert calls[0].arguments["exclude_recipe_ids"] == [7]
    assert calls[0].arguments["scope"] == "local"


def test_menu_progress_counts_distinct_recipes_and_never_cross_counts_by_default():
    plan = MenuExecutionPlan(
        required={"hot_dish": 1, "meat": 1},
        distinct_recipes=True,
        allow_cross_category_counting=False,
    )
    progress = MenuTaskProgress(
        fulfilled={"hot_dish": 0, "meat": 0},
        remaining={"hot_dish": 1, "meat": 1},
        attempted_categories={"hot_dish": 0, "meat": 0},
    )
    calls = [
        ToolCall(
            id="hot",
            tool_name="search_recipes",
            arguments={"category": "hot_dish"},
            purpose="hot",
            success_criteria="one",
        ),
        ToolCall(
            id="meat",
            tool_name="search_recipes",
            arguments={"category": "meat"},
            purpose="meat",
            success_criteria="one",
        ),
    ]
    shared = {
        "id": 1,
        "name": "红烧排骨",
        "categories": ["hot_dish", "meat"],
        "main_ingredients": ["排骨"],
        "safety_status": "eligible",
    }
    observations = [
        Observation(
            call_id=call.id,
            tool_name="search_recipes",
            purpose=call.purpose,
            success_criteria=call.success_criteria,
            ok=True,
            has_data=True,
            summary="candidate",
            data={"items": [shared]},
        )
        for call in calls
    ]

    updated = update_menu_task_progress(
        plan_payload=plan.model_dump(mode="json"),
        progress_payload=progress.model_dump(mode="json"),
        calls=calls,
        observations=observations,
    )

    assert len(updated.selected_recipes) == 1
    assert sum(updated.fulfilled.values()) == 1
    assert updated.complete is False


def test_menu_progress_rejects_unknown_safety_and_deduplicates_across_sources():
    plan = MenuExecutionPlan(required={"hot_dish": 2, "meat": 1})
    progress = MenuTaskProgress(
        fulfilled={"hot_dish": 0, "meat": 0},
        remaining={"hot_dish": 2, "meat": 1},
        attempted_categories={"hot_dish": 0, "meat": 0},
    )
    calls = [
        ToolCall(
            id="hot",
            tool_name="search_recipes",
            arguments={"category": "hot_dish"},
            purpose="hot",
            success_criteria="two",
        ),
        ToolCall(
            id="meat",
            tool_name="search_recipes",
            arguments={"category": "meat"},
            purpose="meat",
            success_criteria="one",
        ),
    ]
    observations = [
        Observation(
            call_id="hot",
            tool_name="search_recipes",
            purpose="hot",
            success_criteria="two",
            ok=True,
            has_data=True,
            summary="database candidates",
            data={
                "items": [
                    {
                        "id": 8,
                        "name": "红烧排骨",
                        "categories": ["hot_dish", "meat"],
                        "main_ingredients": ["排骨"],
                        "safety_status": "eligible",
                    },
                    {
                        "id": 9,
                        "name": "证据不全的菜",
                        "categories": ["hot_dish"],
                        "main_ingredients": [],
                        "safety_status": "unknown",
                    },
                ]
            },
        ),
        Observation(
            call_id="meat",
            tool_name="search_recipes",
            purpose="meat",
            success_criteria="one",
            ok=True,
            has_data=True,
            summary="bundled candidates",
            data={
                "items": [
                    {
                        "name": "红烧排骨",
                        "categories": ["hot_dish", "meat"],
                        "main_ingredients": ["排骨"],
                        "safety_status": "eligible",
                    }
                ]
            },
        ),
    ]

    updated = update_menu_task_progress(
        plan_payload=plan.model_dump(mode="json"),
        progress_payload=progress.model_dump(mode="json"),
        calls=calls,
        observations=observations,
    )

    assert [item.name for item in updated.selected_recipes] == ["红烧排骨"]
    assert updated.fulfilled == {"hot_dish": 1, "meat": 0}


def test_menu_progress_cross_counts_only_when_request_explicitly_allows_it():
    plan = MenuExecutionPlan(
        required={"hot_dish": 1, "meat": 1},
        allow_cross_category_counting=True,
    )
    progress = MenuTaskProgress(
        fulfilled={"hot_dish": 0, "meat": 0},
        remaining={"hot_dish": 1, "meat": 1},
        attempted_categories={"hot_dish": 0, "meat": 0},
    )
    call = ToolCall(
        id="hot",
        tool_name="search_recipes",
        arguments={"category": "hot_dish"},
        purpose="hot",
        success_criteria="one",
    )
    observation = Observation(
        call_id="hot",
        tool_name="search_recipes",
        purpose="hot",
        success_criteria="one",
        ok=True,
        has_data=True,
        summary="candidate",
        data={
            "items": [
                {
                    "id": 1,
                    "name": "红烧排骨",
                    "categories": ["hot_dish", "meat"],
                    "main_ingredients": ["排骨"],
                    "safety_status": "eligible",
                }
            ]
        },
    )

    updated = update_menu_task_progress(
        plan_payload=plan.model_dump(mode="json"),
        progress_payload=progress.model_dump(mode="json"),
        calls=[call],
        observations=[observation],
    )

    assert updated.fulfilled == {"hot_dish": 1, "meat": 1}
    assert updated.complete is True


def test_menu_answer_is_grouped_and_reports_exact_quota_coverage():
    plan = MenuExecutionPlan(
        scenario="农村宴席", required={"cold_dish": 1, "soup": 1}
    )
    progress = MenuTaskProgress(
        fulfilled={"cold_dish": 1, "soup": 0},
        remaining={"cold_dish": 0, "soup": 1},
        selected_recipes=(
            SelectedMenuRecipe(
                name="凉拌豆腐",
                assigned_category="cold_dish",
                categories=("cold_dish", "vegetarian"),
                credited_categories=("cold_dish",),
                main_ingredients=("豆腐", "小葱"),
                evidence_call_id="cold",
            ),
        ),
        attempted_categories={"cold_dish": 1, "soup": 2},
        exhausted_categories=("soup",),
        partial_reason="以下分类在现有来源中候选不足：soup",
    )

    answer = render_menu_plan(
        plan.model_dump(mode="json"), progress.model_dump(mode="json")
    )

    assert "农村宴席" in answer
    assert "凉菜（1/1）" in answer
    assert "汤（0/1）" in answer
    assert "凉拌豆腐（主要食材：豆腐、小葱）" in answer
    assert "汤还缺 1 道" in answer


@pytest.mark.asyncio
async def test_menu_reflector_replans_until_deterministic_goal_is_complete():
    class NoReflectionModel(Model):
        async def reflect(self, **kwargs):
            raise AssertionError("menu completion must be verified by code")

    reflector = create_reflector_node(NoReflectionModel(), Tools())
    progress = MenuTaskProgress(
        fulfilled={"cold_dish": 1, "soup": 0},
        remaining={"cold_dish": 0, "soup": 1},
        attempted_categories={"cold_dish": 1, "soup": 1},
    )

    output = await reflector(
        {
            "menu_task_progress": progress.model_dump(mode="json"),
            "iteration": 1,
            "max_iterations": 4,
        }
    )

    assert output["route"] == "replan"
    assert output["evidence_sufficient"] is False
    assert "soup 仍缺 1 道" in output["missing_information"]


@pytest.mark.asyncio
async def test_menu_reflector_stops_with_partial_result_when_source_is_exhausted():
    class NoReflectionModel(Model):
        async def reflect(self, **kwargs):
            raise AssertionError("exhausted menu must converge without the model")

    reflector = create_reflector_node(NoReflectionModel(), Tools())
    progress = MenuTaskProgress(
        fulfilled={"soup": 2, "hot_dish": 3},
        remaining={"soup": 1, "hot_dish": 0},
        attempted_categories={"soup": 2, "hot_dish": 1},
        exhausted_categories=("soup",),
        partial_reason="以下分类在现有来源中候选不足：soup",
    )

    output = await reflector(
        {
            "menu_task_progress": progress.model_dump(mode="json"),
            "iteration": 2,
            "max_iterations": 4,
        }
    )

    assert output["route"] == "finish"
    assert output["evidence_sufficient"] is False
    assert output["loop_stop_reason"] == "menu_sources_exhausted"
    assert output["missing_information"] == ["soup 仍缺 1 道"]

@pytest.mark.asyncio
async def test_agent_runs_without_workflow_and_enforces_constraints():
    tools = Tools()
    agent = AgentExecutionService(
        build_agent_graph(model_gateway=Model(), tool_executor=tools)
    )
    response = await agent.process(
        "推荐晚餐",
        "independent",
        context=AgentContext(
            dietary_constraints={"active": True, "excluded_ingredients": ["花生"]}
        ),
    )
    assert response.status == "ok"
    assert tools.calls[0].arguments["exclude_ingredients"] == ["花生"]
    assert response.evidence
    assert "蒸土豆" in response.message


@pytest.mark.asyncio
async def test_approval_pause_and_resume_cross_workflow_safety_gate():
    tools = Tools()
    agent = AgentExecutionService(
        build_agent_graph(
            model_gateway=Model(),
            tool_executor=tools,
            checkpointer=MemorySaver(),
            approval_tool_names=frozenset({"recommend_recipes"}),
        )
    )
    response = await agent.process(
        "推荐晚餐",
        "resumable",
        context=AgentContext(
            intent="recommend",
            dietary_constraints={"active": True, "excluded_ingredients": ["花生"]},
        ),
    )
    assert response.metadata["approval_required"]
    assert not tools.calls
    workflow = ChatWorkflow(None, build_resume_workflow(agent=agent))
    result = await workflow.resume("resumable", approved=True)
    assert tools.calls
    assert result.metadata["safety_review"] == "passed"
    assert result.metadata["safe_recipe_names"] == ["蒸土豆"]


@pytest.mark.asyncio
async def test_denied_approval_does_not_execute_tools():
    tools = Tools()
    agent = AgentExecutionService(
        build_agent_graph(
            model_gateway=Model(),
            tool_executor=tools,
            checkpointer=MemorySaver(),
            approval_tool_names=frozenset({"recommend_recipes"}),
        )
    )
    await agent.process("推荐晚餐", "denied")
    result = await ChatWorkflow(None, build_resume_workflow(agent=agent)).resume(
        "denied", approved=False
    )
    assert not tools.calls
    assert result.metadata["approved"] is False
