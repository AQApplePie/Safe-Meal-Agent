import asyncio
import pytest

from safemeal.application.contracts.agent.api import AgentProcessResponse
from safemeal.application.contracts.agent.decisions import Observation
from safemeal.application.contracts.workflow.models import WorkflowRequest
from safemeal.application.contracts.agent.context import AgentContext
from safemeal.application.observability.streaming import (
    emit_answer_chunk,
    use_answer_stream,
)
from safemeal.application.workflow.graph import build_chat_workflow
from safemeal.application.workflow.runner import ChatWorkflow
from safemeal.application.workflow.context.builder import AgentContextBuilder
from safemeal.application.workflow.context.conversation_context import (
    MemoryRelevanceSelector,
)
from safemeal.modules.recipe_catalog.generated_recipe import GeneratedRecipe


class Memory:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.saved = []
        self.events = []

    def load_agent_memories(self, **kwargs):
        self.events.append("load")
        return self.rows

    def load_episodic_memories(self, **kwargs):
        return []

    def remember_from_message(self, **kwargs):
        self.events.append("save")
        self.saved.append(kwargs["message"])


class Agent:
    def __init__(self, result):
        self.result = result
        self.contexts = []

    async def process(self, message, session_id, *, context=None, include_trace=False):
        self.contexts.append(context)
        await emit_answer_chunk("UNREVIEWED_DRAFT")
        return self.result


def evidence(data, tool="recommend_recipes"):
    return Observation(
        call_id="call",
        tool_name=tool,
        purpose="search",
        success_criteria="complete",
        ok=True,
        has_data=True,
        summary="results",
        data=data,
    ).model_dump(mode="json")


def workflow(agent, memory, classifier=None):
    return ChatWorkflow(
        build_chat_workflow(
            agent=agent,
            context_builder=AgentContextBuilder(memory_service=memory),
            memory_service=memory,
            intent_classifier=classifier,
        )
    )


def allergy():
    return {
        "memory_type": "dietary_allergy",
        "memory_key": "花生",
        "memory_value": "用户花生过敏。",
        "memory_metadata": {"excluded_ingredients": ["花生"]},
    }


def recipe(step="将土豆蒸熟。"):
    return GeneratedRecipe(
        name="蒸土豆",
        description="家常菜",
        total_time_minutes=20,
        servings=1,
        difficulty="easy",
        ingredients=[{"name": "土豆", "quantity": 100, "unit": "g"}],
        steps=[{"number": 1, "action": "蒸", "instruction": step}],
        nutrition={},
    )


@pytest.mark.asyncio
async def test_workflow_retains_allergy_and_publishes_only_reviewed_answer():
    agent = Agent(
        AgentProcessResponse(
            message="推荐花生菜",
            evidence=[
                evidence(
                    {
                        "items": [
                            {"name": "花生菜", "ingredients": ["花生"]},
                            {"name": "蒸土豆", "ingredients": ["土豆"]},
                        ]
                    }
                )
            ],
        )
    )
    memory = Memory([allergy()])
    queue = asyncio.Queue()
    with use_answer_stream(queue):
        result = await workflow(agent, memory).run(
            WorkflowRequest(message="推荐晚餐", user_id="u", session_id="s")
        )
    assert queue.empty()
    assert "花生" in agent.contexts[0].dietary_constraints["excluded_ingredients"]
    assert result.metadata["safety_review"] == "passed"
    assert result.metadata["safe_recipe_names"] == ["蒸土豆"]
    assert "推荐花生菜" not in result.message


@pytest.mark.asyncio
async def test_unknown_recipe_fails_closed():
    agent = Agent(
        AgentProcessResponse(
            message="随便吃", evidence=[evidence({"items": [{"name": "神秘菜"}]})]
        )
    )
    result = await workflow(agent, Memory([allergy()])).run(
        WorkflowRequest(message="推荐晚餐", user_id="u", session_id="s")
    )
    assert result.status == "degraded"
    assert result.recipe is None
    assert result.metadata["safety_review"] == "blocked"


@pytest.mark.asyncio
async def test_generated_card_with_forbidden_step_is_removed():
    generated = recipe("加入花生搅拌。")
    agent = Agent(
        AgentProcessResponse(
            message="试试这个",
            recipe=generated,
            metadata={"generated_recipe": generated.model_dump(mode="json")},
            evidence=[evidence(generated.model_dump(mode="json"), "generate_recipe")],
        )
    )
    result = await workflow(agent, Memory([allergy()])).run(
        WorkflowRequest(message="生成一道菜", user_id="u", session_id="s")
    )
    assert result.recipe is None
    assert "generated_recipe" not in result.metadata
    assert result.metadata["safety_review"] == "blocked"


@pytest.mark.asyncio
async def test_valid_generated_card_survives_review():
    generated = recipe()
    agent = Agent(
        AgentProcessResponse(
            message="食谱",
            recipe=generated,
            evidence=[evidence(generated.model_dump(mode="json"), "generate_recipe")],
        )
    )
    result = await workflow(agent, Memory([allergy()])).run(
        WorkflowRequest(message="生成一道菜", user_id="u", session_id="s")
    )
    assert result.recipe == generated
    assert result.metadata["safety_review"] == "passed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "今天我喜欢清淡，推荐晚餐",
        "给朋友做饭，他对花生过敏",
        "假如我对花生过敏，推荐晚餐",
    ],
)
async def test_temporary_and_third_party_facts_are_not_persisted(message):
    memory = Memory()
    agent = Agent(AgentProcessResponse(message="done"))
    await workflow(agent, memory).run(
        WorkflowRequest(message=message, user_id="u", session_id="s")
    )
    assert not memory.saved


@pytest.mark.asyncio
async def test_explicit_memory_load_precedes_save_without_agent_call():
    memory = Memory()
    agent = Agent(AgentProcessResponse(message="unused"))
    await workflow(agent, memory).run(
        WorkflowRequest(message="我喜欢清淡", user_id="u", session_id="s")
    )
    assert memory.events == ["load", "save"]
    assert not agent.contexts


@pytest.mark.asyncio
async def test_retraction_requires_explicit_profile_change():
    memory = Memory([allergy()])
    agent = Agent(AgentProcessResponse(message="unused"))
    result = await workflow(agent, memory).run(
        WorkflowRequest(message="我对花生不过敏", user_id="u", session_id="s")
    )
    assert result.route == "clarify"
    assert not memory.saved
    assert not agent.contexts


def test_hard_memories_never_truncated_by_relevance_limit():
    rows = [dict(allergy(), memory_key=str(i)) for i in range(25)]
    assert len(MemoryRelevanceSelector(limit=2).select("你好", rows)) == 25


@pytest.mark.asyncio
async def test_supplied_context_is_preserved_without_memory_loading():
    agent = Agent(AgentProcessResponse(message="done"))
    context = AgentContext(user_profile={"taste": "清淡"}, user_memories=[allergy()])
    await workflow(agent, Memory()).run(
        WorkflowRequest(
            message="推荐晚餐",
            user_id="u",
            session_id="s",
            context=context,
            use_user_memory=False,
        )
    )
    assert agent.contexts[0].user_profile["taste"] == "清淡"
    assert agent.contexts[0].dietary_constraints["active"]


@pytest.mark.asyncio
async def test_ambiguous_dish_query_uses_independent_intent_classifier():
    from safemeal.application.contracts.workflow.models import IntentDecision

    class Classifier:
        async def classify_intent(self, message, context):
            assert message == "查一下宫保鸡丁"
            return IntentDecision(kind="recipe_detail")

    agent = Agent(AgentProcessResponse(message="食谱详情"))
    result = await workflow(agent, Memory(), Classifier()).run(
        WorkflowRequest(message="查一下宫保鸡丁", user_id="u", session_id="s")
    )
    assert agent.contexts[0].intent == "recipe_detail"
    assert result.message == "食谱详情"


@pytest.mark.asyncio
async def test_intent_classifier_failure_returns_clarification_without_agent():
    class Classifier:
        async def classify_intent(self, message, context):
            raise RuntimeError("provider unavailable")

    agent = Agent(AgentProcessResponse(message="unused"))
    result = await workflow(agent, Memory(), Classifier()).run(
        WorkflowRequest(message="查一下宫保鸡丁", user_id="u", session_id="s")
    )
    assert result.route == "clarify"
    assert not agent.contexts


@pytest.mark.asyncio
async def test_classifier_cannot_publish_a_recipe_as_clarification():
    from safemeal.application.contracts.workflow.models import IntentDecision

    class Classifier:
        async def classify_intent(self, message, context):
            return IntentDecision(kind="clarify", clarification="UNREVIEWED_RECIPE")

    agent = Agent(AgentProcessResponse(message="unused"))
    result = await workflow(agent, Memory([allergy()]), Classifier()).run(
        WorkflowRequest(message="查一下宫保鸡丁", user_id="u", session_id="s")
    )
    assert "UNREVIEWED_RECIPE" not in result.message
    assert not agent.contexts
