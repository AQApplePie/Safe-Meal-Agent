"""Behavioral coverage for Agent intent ownership and bounded context preparation."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from safemeal.agent.runtime.orchestration import build_agent_graph
from safemeal.agent.gateway import AgentExecutionService
from safemeal.agent.contracts.api import AgentProcessResponse
from safemeal.agent.contracts.context import AgentContext
from safemeal.agent.contracts.intent import IntentDecision
from safemeal.agent.contracts.workflow.models import WorkflowRequest
from safemeal.modules.conversation.application.turn_persistence import ChatTurnPersistence
from safemeal.agent.context.history import (
    ConversationHistoryService,
)
from safemeal.modules.conversation.application.chat_exceptions import ChatTurnConflictError
from safemeal.agent.workflow.context.builder import AgentContextBuilder
from safemeal.agent.workflow.nodes.prepare_context import PrepareContextNode
from safemeal.infrastructure.persistence.database import Base
from safemeal.infrastructure.persistence.chat_repository import SqlAlchemyChatUnitOfWork
from test_agent_graph import Model, Tools
from test_workflow import Memory, evidence, workflow


@pytest.mark.asyncio
async def test_independent_agent_classifies_ambiguous_query_and_passes_intent_to_plan():
    class ClassifierModel(Model):
        async def classify_intent(self, message, context):
            assert message == "查一下宫保鸡丁"
            return IntentDecision(kind="recipe_detail")

        async def plan(self, **kwargs):
            task = next(
                o for o in kwargs["observations"] if o.tool_name == "task_context"
            )
            assert task.data["intent"] == "recipe_detail"
            return await super().plan(**kwargs)

    tools = Tools()
    agent = AgentExecutionService(
        build_agent_graph(model_gateway=ClassifierModel(), tool_executor=tools)
    )
    response = await agent.process("查一下宫保鸡丁", "standalone-intent")
    assert response.intent.kind == "recipe_detail"
    assert tools.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [True, False])
async def test_agent_clarification_never_publishes_classifier_free_text(fails):
    class ClassifierModel(Model):
        async def classify_intent(self, message, context):
            if fails:
                raise RuntimeError("unavailable")
            return IntentDecision(kind="clarify", clarification="UNREVIEWED_RECIPE")

        async def plan(self, **kwargs):
            pytest.fail("clarification must not execute recipe planning")

    tools = Tools()
    agent = AgentExecutionService(
        build_agent_graph(model_gateway=ClassifierModel(), tool_executor=tools)
    )
    response = await agent.process("查一下宫保鸡丁", "clarify")
    assert response.intent.kind == "clarify"
    assert "UNREVIEWED_RECIPE" not in response.message
    assert "请补充" in response.message
    assert not tools.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["knowledge", "clarify", "memory", "out_of_scope"])
async def test_non_recipe_label_cannot_bypass_review_of_recipe_evidence(kind):
    class MislabelledAgent:
        async def process(self, *args, **kwargs):
            return AgentProcessResponse(
                message="吃花生菜",
                intent=IntentDecision(kind=kind),
                evidence=[
                    evidence({"items": [{"name": "花生菜", "ingredients": ["花生"]}]})
                ],
            )

    result = await workflow(MislabelledAgent(), Memory()).run(
        WorkflowRequest(
            message="推荐晚餐，我对花生过敏",
            session_id="s",
            user_id="u",
        )
    )
    assert result.metadata["safety_review"] == "blocked"
    assert result.metadata["safe_recipe_names"] == []


@pytest.fixture
def stored_turns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'chat.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def uow():
        return SqlAlchemyChatUnitOfWork(session_factory=factory)

    persistence = ChatTurnPersistence(uow)
    first = persistence.start_turn(None, "owner", "我喜欢清淡")
    persistence.save_agent_response(
        session_id=first.session_id,
        user_id="owner",
        user_message_id=first.user_message_id,
        response_order_index=first.response_order_index,
        response="收到",
    )
    current = persistence.start_turn(first.session_id, "owner", "推荐晚餐")
    persistence.save_agent_response(
        session_id=current.session_id,
        user_id="owner",
        user_message_id=current.user_message_id,
        response_order_index=current.response_order_index,
        response="本轮回复",
    )
    persistence.start_turn(first.session_id, "owner", "后续消息")
    yield uow, current
    engine.dispose()


@pytest.mark.asyncio
async def test_prepare_context_reads_only_prior_history_and_loads_memory_once(
    stored_turns,
):
    uow, turn = stored_turns
    memory = Memory(
        [
            {
                "memory_type": "dietary_allergy",
                "memory_key": "花生",
                "memory_value": "花生过敏",
            }
        ]
    )
    builder = AgentContextBuilder(
        memory_service=memory, history_service=ConversationHistoryService(uow)
    )
    update = await PrepareContextNode(builder)(
        {
            "request": WorkflowRequest(
                message="推荐晚餐",
                user_id="owner",
                session_id=turn.session_id,
                source_message_id=str(turn.user_message_id),
                history=[{"role": "user", "content": "不应覆盖持久化历史"}],
            )
        }
    )
    assert [m["content"] for m in update["context"].conversation_history] == [
        "我喜欢清淡",
        "收到",
    ]
    assert update["context"].user_memories
    assert memory.events == ["load"]
    assert not hasattr(turn, "history")


@pytest.mark.parametrize("wrong_user, wrong_session", [(True, False), (False, True)])
def test_history_anchor_must_belong_to_requested_user_and_session(
    stored_turns, wrong_user, wrong_session
):
    uow, turn = stored_turns
    with pytest.raises(ChatTurnConflictError):
        ConversationHistoryService(uow).load_before_turn(
            user_id="other" if wrong_user else "owner",
            session_id="other" if wrong_session else turn.session_id,
            source_message_id=str(turn.user_message_id),
        )


@pytest.mark.asyncio
async def test_disabling_long_term_memory_still_prepares_history(stored_turns):
    uow, turn = stored_turns
    memory = Memory()
    update = await PrepareContextNode(
        AgentContextBuilder(
            memory_service=memory,
            history_service=ConversationHistoryService(uow),
        )
    )(
        {
            "request": WorkflowRequest(
                message="推荐晚餐",
                user_id="owner",
                session_id=turn.session_id,
                source_message_id=str(turn.user_message_id),
                use_user_memory=False,
                context=AgentContext(user_profile={"taste": "清淡"}),
            )
        }
    )
    assert len(update["context"].conversation_history) == 2
    assert update["context"].user_profile == {"taste": "清淡"}
    assert memory.events == []


@pytest.mark.asyncio
async def test_persisted_chat_runs_prepare_agent_review_and_saves_final_answer(
    stored_turns,
):
    from safemeal.modules.conversation.contracts.chat.turn import ChatRequest
    from safemeal.agent.gateway.chat_turn_service import ChatTurnService
    from safemeal.agent.workflow.graph import build_chat_workflow
    from safemeal.agent.workflow.runner import ChatWorkflow

    uow, previous = stored_turns
    memory = Memory()
    tools = Tools()

    class ContextModel(Model):
        async def plan(self, **kwargs):
            contents = [m["content"] for m in kwargs["conversation_history"]]
            assert "后续消息" in contents
            assert "推荐新的晚餐" not in contents
            return await super().plan(**kwargs)

    agent = AgentExecutionService(
        build_agent_graph(model_gateway=ContextModel(), tool_executor=tools)
    )
    runner = ChatWorkflow(
        build_chat_workflow(
            agent=agent,
            context_builder=AgentContextBuilder(
                memory_service=memory, history_service=ConversationHistoryService(uow)
            ),
            memory_service=memory,
        )
    )
    service = ChatTurnService(persistence=ChatTurnPersistence(uow), workflow=runner)
    response = await service.handle(
        ChatRequest(
            message="推荐新的晚餐",
            user_id="owner",
            session_id=previous.session_id,
        )
    )
    assert response.metadata["safety_review"] == "passed"
    assert response.metadata["safe_recipe_names"] == ["蒸土豆"]
    with uow() as transaction:
        saved = transaction.messages.get(int(response.message_id), user_id="owner")
        assert saved.content == response.message
    assert memory.events == ["load"]
