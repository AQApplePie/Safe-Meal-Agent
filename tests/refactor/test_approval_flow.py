"""Real SQL state and persistent LangGraph checkpoints; deterministic model/tools."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from safemeal.agent.contracts.api import AgentResumeRequest
from safemeal.agent.contracts.context import AgentContext
from safemeal.agent.contracts.decisions import (
    PlanDecision,
    ReflectionDecision,
    ToolCall,
)
from safemeal.agent.gateway.service import AgentExecutionService
from safemeal.agent.gateway.chat_turn_service import ChatTurnService
from safemeal.agent.runtime.orchestration.graph import build_agent_graph
from safemeal.agent.runtime.tools.contracts.base import ToolSpecification, ToolResult
from safemeal.agent.workflow.graph import build_resume_workflow
from safemeal.agent.workflow.runner import ChatWorkflow
from safemeal.infrastructure.persistence.database import Base
from safemeal.infrastructure.persistence.chat_repository import SqlAlchemyChatUnitOfWork
from safemeal.infrastructure.persistence.langgraph_checkpoint import (
    SqliteCheckpointSaver,
)
from safemeal.infrastructure.persistence.checkpoint_serializer import (
    ContractCheckpointSerializer,
)
from safemeal.modules.conversation.application.turn_persistence import (
    ChatTurnPersistence,
)
from safemeal.modules.conversation.application.chat_session_service import (
    ChatSessionService,
)
from safemeal.modules.conversation.application.chat_exceptions import (
    ChatTurnConflictError,
    ChatSessionNotFoundError,
)


class Model:
    async def plan(self, **kwargs):
        return PlanDecision(
            decision="tools",
            rationale="test",
            calls=[
                ToolCall(
                    id="c",
                    tool_name="recommend_recipes",
                    arguments={},
                    purpose="推荐食谱",
                    success_criteria="complete ingredients",
                )
            ],
        )

    async def reflect(self, **kwargs):
        return ReflectionDecision(
            decision="finish", rationale="complete", evidence_sufficient=True
        )

    async def answer(self, **kwargs):
        return "推荐蒸土豆"


class Tools:
    def __init__(self):
        self.calls = []

    def specifications(self):
        return [
            ToolSpecification(
                name="recommend_recipes",
                description="test",
                arguments_schema={"type": "object"},
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


@pytest.fixture
def environment(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'app.sqlite'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    def uow():
        return SqlAlchemyChatUnitOfWork(session_factory=factory)

    persistence = ChatTurnPersistence(uow)
    sessions = ChatSessionService(uow_factory=uow)
    tools = Tools()

    def make_agent():
        return AgentExecutionService(
            build_agent_graph(
                model_gateway=Model(),
                tool_executor=tools,
                checkpointer=SqliteCheckpointSaver(
                    tmp_path / "checkpoints.sqlite",
                    serde=ContractCheckpointSerializer(),
                ),
                approval_tool_names=frozenset({"recommend_recipes"}),
            )
        )

    yield persistence, sessions, tools, make_agent
    engine.dispose()


async def paused(environment):
    persistence, _, tools, make_agent = environment
    turn = persistence.start_turn(None, "owner", "推荐晚餐")
    response = await make_agent().process(
        "推荐晚餐", turn.session_id, context=AgentContext(intent="recommend")
    )
    assert response.metadata["approval_required"] and not tools.calls
    message_id = persistence.save_agent_response(
        session_id=turn.session_id,
        user_id="owner",
        user_message_id=turn.user_message_id,
        response_order_index=turn.response_order_index,
        response=response.message,
        metadata=response.metadata,
    )
    request = AgentResumeRequest(
        session_id=turn.session_id,
        message_id=int(message_id),
        approval_id=response.metadata["approval_id"],
        approved=True,
    )
    # Rebuild both the Agent and checkpoint adapter: no in-memory resume state.
    workflow = ChatWorkflow(None, build_resume_workflow(agent=make_agent()))
    return request, ChatTurnService(persistence=persistence, workflow=workflow)


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [True, False])
async def test_restart_resume_persists_reviewed_response_once(environment, approved):
    persistence, sessions, tools, _ = environment
    request, service = await paused(environment)
    request.approved = approved
    result = await service.resume(request, user_id="owner")
    assert result.status != "error"
    assert bool(tools.calls) is approved
    assert result.metadata["safety_review"] == (
        "passed" if approved else "no_recommendation"
    )
    history = sessions.list_messages(
        request.session_id, user_id="owner", offset=0, limit=100
    )
    assert len(history) == 2
    assert history[-1].content == result.message
    assert history[-1].message_metadata["approval_state"] == (
        "approved" if approved else "rejected"
    )
    with pytest.raises(ChatTurnConflictError):
        await service.resume(request, user_id="owner")
    assert len(result.metadata["approval_history"]) == 1
    assert result.metadata["approval_history"][0]["approved"] is approved
    assert len(tools.calls) == int(approved)
    persistence.start_turn(request.session_id, "owner", "下一条")


@pytest.mark.asyncio
async def test_pending_blocks_new_turn_and_clear_and_cross_user(environment):
    persistence, sessions, _, _ = environment
    request, service = await paused(environment)
    with pytest.raises(ChatTurnConflictError):
        persistence.start_turn(request.session_id, "owner", "覆盖旧任务")
    with pytest.raises(ChatTurnConflictError):
        sessions.clear_messages(request.session_id, user_id="owner")
    with pytest.raises(ChatSessionNotFoundError):
        await service.resume(request, user_id="other")
    with pytest.raises(ChatTurnConflictError):
        await service.resume(
            request.model_copy(update={"approval_id": "obsolete"}), user_id="owner"
        )
    assert (await service.resume(request, user_id="owner")).status != "error"


@pytest.mark.asyncio
async def test_parallel_claim_has_single_winner(environment):
    persistence, _, _, _ = environment
    request, _ = await paused(environment)

    def claim():
        try:
            persistence.claim_approval(
                session_id=request.session_id,
                user_id="owner",
                message_id=request.message_id,
                approval_id=request.approval_id,
                approved=True,
            )
            return True
        except ChatTurnConflictError:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        winners = list(pool.map(lambda _: claim(), range(4)))
    assert winners.count(True) == 1
    history = environment[1].list_messages(
        request.session_id, user_id="owner", offset=0, limit=100
    )
    assert history[-1].message_metadata["approval_history"][0]["approved"] is True
    assert history[-1].turn_status == "processing"


@pytest.mark.asyncio
async def test_resume_failure_is_persisted_and_not_replayed(environment):
    from safemeal.agent.contracts.api import AgentProcessResponse

    persistence, sessions, tools, _ = environment
    request, _ = await paused(environment)

    class Broken:
        async def resume(self, *args, **kwargs):
            return AgentProcessResponse(
                status="error", message="模型失败", error_code="agent_timeout"
            )

    service = ChatTurnService(persistence=persistence, workflow=Broken())
    response = await service.resume(request, user_id="owner")
    assert response.metadata["approval_state"] == "failed"
    with pytest.raises(ChatTurnConflictError):
        await service.resume(request, user_id="owner")
    assert not tools.calls
    assert (
        sessions.list_messages(request.session_id, user_id="owner", offset=0, limit=10)[
            -1
        ].turn_status
        == "failed"
    )


def test_approval_requires_explicit_boolean_and_identifiers():
    from pydantic import ValidationError

    for payload in [
        dict(session_id="s", approved=True),
        dict(session_id="s", approved="false", message_id=2, approval_id="id"),
    ]:
        with pytest.raises(ValidationError):
            AgentResumeRequest(**payload)


@pytest.mark.asyncio
async def test_http_approval_status_codes_and_persisted_history(environment):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from safemeal.interfaces.http.routers.chat import router
    from safemeal.interfaces.http.authentication import Principal, get_current_principal
    from safemeal.interfaces.http.dependencies import (
        get_chat_turn_service,
        get_chat_session_service,
    )

    _, sessions, tools, _ = environment
    request, service = await paused(environment)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/chat")
    app.dependency_overrides[get_chat_turn_service] = lambda: service
    app.dependency_overrides[get_chat_session_service] = lambda: sessions
    from types import SimpleNamespace
    from safemeal.interfaces.http.platform_dependencies import (
        get_auth_service,
        get_http_settings,
    )

    app.dependency_overrides[get_auth_service] = lambda: SimpleNamespace(
        authenticate_access_token=lambda _: None
    )
    app.dependency_overrides[get_http_settings] = lambda: SimpleNamespace(
        ENABLE_OIDC=False
    )
    payload = request.model_dump()
    with TestClient(app) as client:
        assert client.post("/api/v1/chat/resume", json=payload).status_code == 401

        # Principal.storage_subject is tenant:subject; use a scoped test principal.
        class Owner:
            tenant_id = "default"
            storage_subject = "owner"

        app.dependency_overrides[get_current_principal] = lambda: Principal(
            subject="other", tenant_id="tenant"
        )
        assert client.post("/api/v1/chat/resume", json=payload).status_code == 404
        app.dependency_overrides[get_current_principal] = lambda: Owner()
        assert (
            client.post(
                "/api/v1/chat/resume", json={**payload, "approved": "false"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/chat/resume", json={**payload, "approval_id": "old"}
            ).status_code
            == 409
        )
        assert (
            client.delete(
                f"/api/v1/chat/sessions/{request.session_id}/messages"
            ).status_code
            == 409
        )
        result = client.post("/api/v1/chat/resume", json=payload)
        assert result.status_code == 200
        assert result.json()["metadata"]["safety_review"] == "passed"
        assert client.post("/api/v1/chat/resume", json=payload).status_code == 409
        history = client.get(f"/api/v1/chat/history/{request.session_id}").json()
        assert history[-1]["content"] == result.json()["message"]
        assert history[-1]["message_metadata"]["approval_state"] == "approved"
        assert len(tools.calls) == 1


@pytest.mark.asyncio
async def test_new_approval_round_invalidates_old_token(environment):
    from safemeal.agent.contracts.api import AgentProcessResponse

    persistence, _, _, _ = environment
    request, _ = await paused(environment)

    class Again:
        async def resume(self, *args, **kwargs):
            return AgentProcessResponse(
                status="degraded",
                message="另一个操作等待确认",
                metadata={
                    "approval_required": True,
                    "approval_id": "next-round",
                    "pending_calls": [],
                },
            )

    service = ChatTurnService(persistence=persistence, workflow=Again())
    result = await service.resume(request, user_id="owner")
    assert result.metadata["approval_state"] == "pending"
    with pytest.raises(ChatTurnConflictError):
        await service.resume(request, user_id="owner")
    persistence.claim_approval(
        session_id=request.session_id,
        user_id="owner",
        message_id=request.message_id,
        approval_id="next-round",
        approved=True,
    )


@pytest.mark.asyncio
async def test_missing_checkpoint_cannot_publish_success(environment, tmp_path):
    persistence, _, tools, _ = environment
    request, _ = await paused(environment)
    agent = AgentExecutionService(
        build_agent_graph(
            model_gateway=Model(),
            tool_executor=tools,
            checkpointer=SqliteCheckpointSaver(tmp_path / "missing.sqlite"),
            approval_tool_names=frozenset({"recommend_recipes"}),
        )
    )
    service = ChatTurnService(
        persistence=persistence,
        workflow=ChatWorkflow(None, build_resume_workflow(agent=agent)),
    )
    result = await service.resume(request, user_id="owner")
    assert result.status == "error"
    assert result.error_code == "approval_checkpoint_unavailable"
    assert not tools.calls
    with pytest.raises(ChatTurnConflictError):
        await service.resume(request, user_id="owner")


def test_internal_string_decision_does_not_approve(monkeypatch):
    from safemeal.agent.runtime.orchestration.nodes import approval

    monkeypatch.setattr(approval, "interrupt", lambda _: {"approved": "false"})
    call = ToolCall(
        id="c",
        tool_name="recommend_recipes",
        arguments={},
        purpose="test",
        success_criteria="test",
    )
    result = approval.create_approval_node(frozenset({"recommend_recipes"}))(
        {"pending_calls": [call]}
    )
    assert result["pending_calls"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["tool", "model_timeout"])
async def test_checkpoint_resume_faults_fail_closed(environment, fault):
    import asyncio

    persistence, sessions, tools, make_agent = environment
    request, _ = await paused(environment)
    if fault == "tool":

        async def fail(calls):
            tools.calls.extend(calls)
            raise RuntimeError("owned synthetic tool failure")

        tools.invoke_many = fail
        agent = make_agent()
    else:
        model_calls = []

        async def slow(calls):
            tools.calls.extend(calls)
            return [
                ToolResult(
                    call_id=c.id,
                    tool_name=c.tool_name,
                    ok=True,
                    data={},
                )
                for c in calls
            ]

        tools.invoke_many = slow

        class SlowModel(Model):
            async def answer(self, **kwargs):
                model_calls.append("answer")
                await asyncio.sleep(1)
                return "迟到的回答"

        agent = AgentExecutionService(
            build_agent_graph(
                model_gateway=SlowModel(),
                tool_executor=tools,
                checkpointer=make_agent()._graph.checkpointer,
                approval_tool_names=frozenset({"recommend_recipes"}),
            ),
            timeout_seconds=0.15,
        )
    response = await ChatTurnService(
        persistence=persistence,
        workflow=ChatWorkflow(None, build_resume_workflow(agent=agent)),
    ).resume(request, user_id="owner")
    if fault == "model_timeout":
        assert model_calls == ["answer"]
        assert response.error_code == "agent_timeout"
    assert response.status == "error"
    assert response.recipe is None
    assert response.metadata["approval_state"] == "failed"
    assert (
        sessions.list_messages(request.session_id, user_id="owner", offset=0, limit=10)[
            -1
        ].turn_status
        == "failed"
    )
    with pytest.raises(ChatTurnConflictError):
        await ChatTurnService(
            persistence=persistence,
            workflow=ChatWorkflow(None, build_resume_workflow(agent=agent)),
        ).resume(request, user_id="owner")


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [True, False])
async def test_generation_tool_has_same_approval_and_final_safety_boundary(
    tmp_path, approved
):
    from safemeal.modules.recipe.contracts.generation import RecipeGenerationRequest
    from safemeal.modules.recipe.contracts.generated import GeneratedRecipe

    class GenerationModel(Model):
        async def plan(self, **kwargs):
            return PlanDecision(
                decision="tools",
                rationale="generate",
                calls=[
                    ToolCall(
                        id="generation",
                        tool_name="generate_recipe",
                        arguments={"requirements": "生成一道土豆食谱"},
                        purpose="生成食谱",
                        success_criteria="valid recipe",
                    )
                ],
            )

    class GenerationTools(Tools):
        def specifications(self):
            return [
                ToolSpecification(
                    name="generate_recipe",
                    description="generate",
                    arguments_schema=RecipeGenerationRequest.model_json_schema(),
                )
            ]

        async def invoke_many(self, calls):
            self.calls.extend(calls)
            recipe = GeneratedRecipe(
                name="蒸土豆",
                description="隔离测试食谱",
                total_time_minutes=20,
                servings=1,
                difficulty="easy",
                ingredients=[{"name": "土豆", "quantity": 100, "unit": "g"}],
                steps=[
                    {
                        "number": 1,
                        "action": "蒸",
                        "instruction": "蒸熟土豆",
                        "duration_minutes": 20,
                    }
                ],
                nutrition={},
            )
            return [
                ToolResult(
                    call_id=c.id,
                    tool_name=c.tool_name,
                    ok=True,
                    data=recipe.model_dump(mode="json"),
                )
                for c in calls
            ]

    tools = GenerationTools()
    agent = AgentExecutionService(
        build_agent_graph(
            model_gateway=GenerationModel(),
            tool_executor=tools,
            checkpointer=SqliteCheckpointSaver(
                tmp_path / "generation.sqlite", serde=ContractCheckpointSerializer()
            ),
            approval_tool_names=frozenset({"generate_recipe"}),
        )
    )
    pending = await agent.process("生成一道土豆食谱", "generation")
    assert pending.metadata["approval_required"] and not tools.calls
    assert pending.metadata["pending_calls"][0]["tool_name"] == "generate_recipe"
    result = await ChatWorkflow(None, build_resume_workflow(agent=agent)).resume(
        "generation", approved=approved
    )
    assert bool(tools.calls) is approved
    if approved:
        assert result.recipe is not None
        assert result.metadata["safety_review"] == "passed"
    else:
        assert result.recipe is None


def test_unfinished_turn_cannot_overwrite_approval_checkpoint(environment):
    persistence, _, _, _ = environment
    turn = persistence.start_turn(None, "owner", "第一个任务")
    with pytest.raises(ChatTurnConflictError):
        persistence.start_turn(turn.session_id, "owner", "并发覆盖检查点")
    persistence.mark_turn_failed(
        session_id=turn.session_id,
        user_id="owner",
        user_message_id=turn.user_message_id,
    )
    persistence.start_turn(turn.session_id, "owner", "已确认失败后的新任务")
