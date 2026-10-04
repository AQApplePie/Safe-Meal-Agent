"""Regression coverage for the lightweight request-understanding boundary."""

import pytest

from safemeal.application.contracts.agent.api import AgentProcessResponse
from safemeal.application.contracts.workflow.models import WorkflowRequest
from safemeal.application.contracts.workflow.request_frame import (
    RequestFrame,
    RequestTask,
)
from safemeal.application.service.chat.request_understanding import (
    RequestUnderstandingService,
)
from safemeal.application.workflow.context.builder import AgentContextBuilder
from safemeal.application.workflow.graph import build_chat_workflow
from safemeal.application.workflow.runner import ChatWorkflow


class SelectiveMemory:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.requested_types = []
        self.episodic_loads = 0

    def load_agent_memories_by_types(self, *, memory_types, **kwargs):
        self.requested_types.append(set(memory_types))
        return [row for row in self.rows if row["memory_type"] in memory_types]

    def load_agent_memories(self, **kwargs):
        raise AssertionError("selective workflow must not load all memories")

    def load_episodic_memories(self, **kwargs):
        self.episodic_loads += 1
        return []

    def remember_from_message(self, **kwargs):
        return []


class CapturingAgent:
    def __init__(self):
        self.calls = []

    async def process(self, message, session_id, *, context=None):
        self.calls.append((message, context))
        return AgentProcessResponse(message="没有找到可核验的食谱。")


class FixedGateway:
    backend_name = "test-tiny-model"

    def __init__(self, frame):
        self.frame = frame
        self.recent_context = None

    async def understand(self, message, recent_context):
        self.recent_context = list(recent_context)
        return self.frame


def make_workflow(memory, agent, gateway=None, threshold=0.7):
    return ChatWorkflow(
        build_chat_workflow(
            agent=agent,
            context_builder=AgentContextBuilder(memory_service=memory),
            memory_service=memory,
            request_understanding_gateway=gateway,
            request_understanding_confidence_threshold=threshold,
        )
    )


def memory(memory_type, key):
    return {
        "memory_type": memory_type,
        "memory_key": key,
        "memory_value": key,
    }


def test_recipe_detail_frame_keeps_target_and_requested_field():
    frame = RequestUnderstandingService().understand("水煮鱼的材料是什么？")
    assert frame.primary_task == "recipe_detail"
    assert frame.target.recipe_name == "水煮鱼"
    assert frame.requested_fields == ("ingredients",)


@pytest.mark.parametrize(
    "message",
    [
        "请告诉我柠檬蒸三文鱼的做法",
        "麻烦介绍一下柠檬蒸三文鱼的步骤",
        "能否查询柠檬蒸三文鱼的材料",
        "我想知道柠檬蒸三文鱼的做法",
    ],
)
def test_recipe_detail_removes_conversational_prefix_from_exact_name(message):
    frame = RequestUnderstandingService().understand(message)

    assert frame.primary_task == "recipe_detail"
    assert frame.target.recipe_name == "柠檬蒸三文鱼"
    assert frame.exact_match_required is True


def test_memory_update_and_business_task_are_independent_dimensions():
    frame = RequestUnderstandingService().understand(
        "我爱吃鱼，水煮鱼的材料是什么？"
    )
    assert frame.primary_task == "recipe_detail"
    assert frame.target.recipe_name == "水煮鱼"
    assert [(item.kind, item.value) for item in frame.memory_updates] == [
        ("preference", "鱼")
    ]


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("请给我推荐一份没有辣椒的鱼", 1),
        ("推荐3道家常菜", 3),
        ("推荐几道家常菜", 3),
    ],
)
def test_recommendation_count_is_understood(message, expected):
    frame = RequestUnderstandingService().understand(message)

    assert frame.primary_task == "recipe_recommendation"
    assert frame.recommendation_count == expected


def test_simple_count_stays_a_normal_recommendation():
    frame = RequestUnderstandingService().understand("给我推荐三道鱼")

    assert frame.primary_task == "recipe_recommendation"
    assert frame.recommendation_count == 3
    assert frame.menu_planning is None


def test_composite_banquet_request_produces_deterministic_category_quotas():
    frame = RequestUnderstandingService().understand(
        "给农村宴席安排三道凉菜、三道热菜、三道汤"
    )

    assert frame.primary_task == "menu_planning"
    assert frame.scenario == "农村宴席"
    assert frame.recommendation_count == 9
    assert frame.menu_planning is not None
    assert {
        item.category: item.count for item in frame.menu_planning.category_quotas
    } == {"cold_dish": 3, "hot_dish": 3, "soup": 3}
    assert frame.menu_planning.distinct_recipes is True
    assert frame.menu_planning.allow_cross_category_counting is False


@pytest.mark.asyncio
async def test_allergy_update_is_an_immediate_constraint_for_recommendation():
    memory_store = SelectiveMemory()
    agent = CapturingAgent()
    await make_workflow(memory_store, agent).run(
        WorkflowRequest(
            message="我对花生过敏，有没有什么没有花生的菜？",
            user_id="u",
            session_id="s",
        )
    )
    frame = agent.calls[0][1].request_frame
    assert frame.primary_task == "recipe_recommendation"
    assert ("allergy", "花生") in [
        (item.kind, item.value) for item in frame.memory_updates
    ]
    assert "花生" in agent.calls[0][1].dietary_constraints["excluded_ingredients"]


@pytest.mark.asyncio
async def test_nutrition_query_does_not_load_preferences_or_episodes():
    memory_store = SelectiveMemory(
        [memory("taste_preference", "鱼"), memory("conversation_episode", "old")]
    )
    agent = CapturingAgent()
    await make_workflow(memory_store, agent).run(
        WorkflowRequest(
            message="100g鸡胸肉大约多少蛋白质？", user_id="u", session_id="s"
        )
    )
    assert memory_store.requested_types == [set()]
    assert memory_store.episodic_loads == 0
    assert agent.calls[0][1].user_memories == []


@pytest.mark.asyncio
async def test_recommendation_loads_preferences_and_hard_safety_only():
    memory_store = SelectiveMemory(
        [
            memory("taste_preference", "鱼"),
            memory("dietary_allergy", "花生"),
            memory("conversation_episode", "old"),
        ]
    )
    agent = CapturingAgent()
    await make_workflow(memory_store, agent).run(
        WorkflowRequest(message="给我推荐几道家常菜。", user_id="u", session_id="s")
    )
    requested = memory_store.requested_types[0]
    assert {"taste_preference", "dietary_allergy", "dietary_restriction"} <= requested
    assert "conversation_episode" not in requested
    assert memory_store.episodic_loads == 0


@pytest.mark.asyncio
async def test_contextual_safety_question_uses_recent_turns_and_falls_back():
    memory_store = SelectiveMemory()
    agent = CapturingAgent()
    gateway = FixedGateway(
        RequestFrame(
            tasks=(RequestTask(kind="food_safety"),),
            context_needs=("recent_conversation",),
            confidence=0.5,
            understanding_status="accepted",
            backend="test-tiny-model",
        )
    )
    result = await make_workflow(memory_store, agent, gateway).run(
        WorkflowRequest(
            message="那这个我能吃吗？",
            user_id="u",
            session_id="s",
            history=[
                {"role": "user", "content": "推荐一道鱼菜"},
                {"role": "assistant", "content": "推荐清蒸鲈鱼"},
            ],
        )
    )
    assert gateway.recent_context[-1]["content"] == "推荐清蒸鲈鱼"
    assert agent.calls[0][0] == "那这个我能吃吗？"
    assert result.metadata["understanding_status"] == "low_confidence"
    assert result.metadata["fallback_used"] is True


@pytest.mark.asyncio
async def test_low_confidence_reuses_agent_with_original_query_and_same_graph():
    memory_store = SelectiveMemory()
    agent = CapturingAgent()
    gateway = FixedGateway(
        RequestFrame(
            tasks=(RequestTask(kind="clarify"),),
            confidence=0.2,
            backend="test-tiny-model",
        )
    )
    result = await make_workflow(memory_store, agent, gateway).run(
        WorkflowRequest(message="随便整点那个", user_id="u", session_id="s")
    )
    assert agent.calls[0][0] == "随便整点那个"
    assert agent.calls[0][1].request_frame.understanding_status == "low_confidence"
    assert result.metadata["fallback_used"] is True


@pytest.mark.asyncio
async def test_safety_override_loads_allergy_when_tiny_model_omits_it():
    memory_store = SelectiveMemory([memory("dietary_allergy", "花生")])
    agent = CapturingAgent()
    gateway = FixedGateway(
        RequestFrame(
            tasks=(RequestTask(kind="recipe_recommendation"),),
            context_needs=(),
            confidence=0.99,
            backend="test-tiny-model",
        )
    )
    await make_workflow(memory_store, agent, gateway).run(
        WorkflowRequest(message="推荐一道晚饭", user_id="u", session_id="s")
    )
    assert "dietary_allergy" in memory_store.requested_types[0]
    assert "花生" in agent.calls[0][1].dietary_constraints["excluded_ingredients"]
