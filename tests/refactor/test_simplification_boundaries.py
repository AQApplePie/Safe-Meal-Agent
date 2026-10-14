"""Protect shared request constraints and completion publication after resume."""

import asyncio

import pytest
from langgraph.checkpoint.memory import MemorySaver

from safemeal.agent.contracts.context import AgentContext
from safemeal.agent.gateway.service import AgentExecutionService
from safemeal.agent.runtime.orchestration import build_agent_graph
from safemeal.agent.runtime.tools.contracts.base import ToolResult
from safemeal.agent.safety.dietary_safety_service import DietarySafetyService
from safemeal.agent.understanding.request_understanding import (
    RequestUnderstandingService,
)
from safemeal.agent.workflow.graph import build_resume_workflow
from safemeal.agent.workflow.runner import ChatWorkflow
from test_agent_graph import Model, Tools


@pytest.mark.asyncio
async def test_standalone_agent_resolves_current_allergy_without_mutating_context():
    tools = Tools()
    context = AgentContext()
    agent = AgentExecutionService(
        build_agent_graph(model_gateway=Model(), tool_executor=tools)
    )
    response = await agent.process("推荐晚餐，我对花生过敏", "allergy", context=context)
    assert "花生" in tools.calls[0].arguments["exclude_ingredients"]
    assert response.metadata["resolved_constraints"]["allergies"]["active"]
    assert context.requirements is None


@pytest.mark.asyncio
async def test_resolved_input_is_not_reinterpreted(monkeypatch):
    context = AgentContext()
    context.requirements = DietarySafetyService().resolve_constraints(
        "花生过敏", context
    )

    def forbidden(*args, **kwargs):
        pytest.fail("resolved requirements must be consumed without text parsing")

    monkeypatch.setattr(DietarySafetyService, "resolve_constraints", forbidden)
    tools = Tools()
    response = await AgentExecutionService(
        build_agent_graph(model_gateway=Model(), tool_executor=tools)
    ).process("推荐晚餐", "frozen", context=context)
    assert response.status == "ok"
    assert "花生" in tools.calls[0].arguments["exclude_ingredients"]


@pytest.mark.asyncio
async def test_partial_count_survives_checkpoint_resume_and_final_safety():
    class PartialTools(Tools):
        async def invoke_many(self, calls):
            self.calls.extend(calls)
            return [
                ToolResult(
                    call_id=c.id,
                    tool_name=c.tool_name,
                    ok=True,
                    data={
                        "items": [{"name": "清蒸鱼", "ingredients": ["鱼"]}],
                        "requested_count": 4,
                        "fulfilled_count": 1,
                        "status": "PARTIAL",
                    },
                )
                for c in calls
            ]

    tools = PartialTools()
    frame = RequestUnderstandingService().understand("推荐四道鱼")
    agent = AgentExecutionService(
        build_agent_graph(
            model_gateway=Model(),
            tool_executor=tools,
            checkpointer=MemorySaver(),
            approval_tool_names=frozenset({"recommend_recipes"}),
        )
    )
    pending = await agent.process(
        "推荐四道鱼", "partial", context=AgentContext(request_frame=frame)
    )
    assert pending.metadata["approval_required"]
    assert not tools.calls
    response = await ChatWorkflow(None, build_resume_workflow(agent=agent)).resume(
        "partial", approved=True
    )
    assert response.status == "degraded"
    assert response.metadata["recommendation_completion"] == {
        "requested": 4,
        "fulfilled": 1,
        "complete": False,
    }
    assert response.metadata["evidence_sufficient"] is False
    assert response.metadata["tool_trace"]
    assert "部分结果" in response.message


@pytest.mark.asyncio
async def test_resume_preserves_menu_metadata_and_display_order():
    context = AgentContext()
    context.requirements = DietarySafetyService().resolve_constraints("", context)
    plan = {"required": {"meat": 2}}
    progress = {"remaining": {"meat": 1}, "complete": False}

    class CompletedGraph:
        async def ainvoke(self, *args, **kwargs):
            return {
                "messages": [{"role": "assistant", "content": "1.「清蒸鱼」"}],
                "agent_context": context.model_dump(mode="json"),
                "question": "两道荤菜",
                "menu_execution_plan": plan,
                "menu_task_progress": progress,
                "evidence_sufficient": False,
                "tool_trace": [{"tool": "search_recipes"}],
            }

    response = (
        await AgentExecutionService(CompletedGraph()).resume("menu", approved=True)
    ).response
    assert response.metadata["active_menu"] == {"plan": plan, "progress": progress}
    assert response.metadata["rendered_recipe_refs"] == [
        {"position": 1, "name": "清蒸鱼"}
    ]
    assert response.metadata["tool_trace"]


@pytest.mark.asyncio
async def test_resume_timeout_has_specific_error_code():
    class SlowGraph:
        async def ainvoke(self, *args, **kwargs):
            await asyncio.sleep(1)

    response = (
        await AgentExecutionService(SlowGraph(), timeout_seconds=0.001).resume(
            "timeout", approved=True
        )
    ).response
    assert response.status == "error"
    assert response.error_code == "agent_timeout"


@pytest.mark.asyncio
async def test_resume_timeout_also_bounds_waiting_for_capacity():
    class NeverInvoked:
        async def ainvoke(self, *args, **kwargs):
            pytest.fail("capacity must be acquired before invoking the graph")

    agent = AgentExecutionService(
        NeverInvoked(), timeout_seconds=0.001, max_concurrency=1
    )
    async with agent._concurrency:
        resumed = await asyncio.wait_for(agent.resume("capacity", approved=True), 0.1)
    assert resumed.response.error_code == "agent_timeout"


def test_structured_frame_allergy_is_resolved_by_the_shared_service():
    from safemeal.shared.contracts.request_frame import CurrentConstraint, RequestFrame

    context = AgentContext(
        request_frame=RequestFrame(
            current_constraints=(CurrentConstraint(kind="allergy", value="花生"),),
        )
    )
    requirements = DietarySafetyService().resolve_constraints("推荐晚餐", context)
    assert "花生" in requirements.allergies.excluded_ingredients
