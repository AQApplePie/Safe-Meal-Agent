import pytest
from langgraph.checkpoint.memory import MemorySaver
from safemeal.application.agent.graph import build_agent_graph
from safemeal.application.agent.execution_service import AgentExecutionService
from safemeal.application.contracts.agent.context import AgentContext
from safemeal.application.contracts.agent.decisions import (
    PlanDecision,
    ToolCall,
    ReflectionDecision,
)
from safemeal.application.contracts.tools.base import ToolResult, ToolSpecification
from safemeal.application.workflow.graph import build_resume_workflow
from safemeal.application.workflow.runner import ChatWorkflow


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
