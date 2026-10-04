from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from safemeal.application.contracts.tools.base import ToolResult
from safemeal.infrastructure.persistence.checkpoint_serializer import (
    ContractCheckpointSerializer,
)
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from typing import TypedDict
from safemeal.infrastructure.persistence.threaded_checkpoint import (
    ThreadedCheckpointSaver,
)
from safemeal.application.contracts.agent.menu_planning import initialize_menu_task
from safemeal.application.contracts.workflow.request_frame import (
    CategoryQuota,
    MenuPlanningRequirements,
)


@pytest.mark.parametrize(
    "legacy_module",
    ["safemeal.shared.contracts.tools", "safemeal.application.contracts.tools"],
)
@pytest.mark.parametrize("encoding", ["msgpack", "json"])
def test_existing_checkpoints_can_read_relocated_tool_contracts(
    legacy_module, encoding
):
    original = ToolResult.__module__
    try:
        ToolResult.__module__ = legacy_module
        value = ToolResult(
            call_id="a",
            tool_name="get_recipe",
            ok=True,
            data={"text": "safemeal.shared.contracts.tools"},
        )
        serializer = JsonPlusSerializer()
        payload = {"results": [value]}
        encoded = (
            serializer.dumps_typed(payload)
            if encoding == "msgpack"
            else ("json", serializer.dumps(payload))
        )
    finally:
        ToolResult.__module__ = original
    restored = ContractCheckpointSerializer().loads_typed(encoded)
    assert isinstance(restored["results"][0], ToolResult)
    assert restored["results"][0].data["text"] == "safemeal.shared.contracts.tools"


class CounterState(TypedDict):
    count: int


@pytest.mark.asyncio
async def test_sync_checkpoint_adapter_supports_async_graph_execution():
    saver = ThreadedCheckpointSaver(MemorySaver())
    graph = StateGraph(CounterState)
    graph.add_node("increment", lambda state: {"count": state["count"] + 1})
    graph.add_edge(START, "increment")
    graph.add_edge("increment", END)
    compiled = graph.compile(checkpointer=saver)
    config = {"configurable": {"thread_id": "sync-adapter"}}
    assert (await compiled.ainvoke({"count": 1}, config=config))["count"] == 2
    assert (await saver.aget_tuple(config)).checkpoint["channel_values"]["count"] == 2


@pytest.mark.parametrize("encoding", ["msgpack", "json"])
@pytest.mark.parametrize(
    "kind", ["constraint", "generated_ingredient", "memory", "safety"]
)
def test_legacy_domain_values_survive_modules_removal(kind, encoding):
    from safemeal.application.contracts.dietary_safety.constraints import (
        DietaryConstraint,
    )
    from safemeal.application.contracts.dietary_safety.models import (
        SafetyDecision,
        SafetyStatus,
    )
    from safemeal.application.contracts.recipes.generated import GeneratedIngredient
    from safemeal.application.contracts.memory.extraction import MemoryCandidate

    values = {
        "constraint": (
            DietaryConstraint(active=True, excluded_ingredients=["花生"]),
            "safemeal.modules.dietary_safety.dietary_constraints",
        ),
        "generated_ingredient": (
            GeneratedIngredient(name="土豆", quantity="100", unit="g"),
            "safemeal.modules.recipe_catalog.generated_recipe",
        ),
        "memory": (
            MemoryCandidate("taste_preference", "清淡", "偏好清淡", 0.8),
            "safemeal.modules.user_memory.memory_models",
        ),
        "safety": (
            SafetyDecision(SafetyStatus.SAFE),
            "safemeal.modules.dietary_safety.recipe_safety",
        ),
    }
    value, legacy_module = values[kind]
    cls = type(value)
    original = cls.__module__
    try:
        cls.__module__ = legacy_module
        serializer = JsonPlusSerializer()
        payload = {"value": value, "text": legacy_module}
        encoded = (
            serializer.dumps_typed(payload)
            if encoding == "msgpack"
            else ("json", serializer.dumps(payload))
        )
    finally:
        cls.__module__ = original
    restored = ContractCheckpointSerializer().loads_typed(encoded)
    assert isinstance(restored["value"], cls)
    # JsonPlus normalizes tuples in plain dataclasses to lists. Compare with a
    # round trip using the current path, so relocation preserves upstream behavior.
    current_payload = {"value": value, "text": legacy_module}
    current_encoded = (
        serializer.dumps_typed(current_payload)
        if encoding == "msgpack"
        else ("json", serializer.dumps(current_payload))
    )
    assert restored["value"] == serializer.loads_typed(current_encoded)["value"]
    assert restored["text"] == legacy_module


@pytest.mark.parametrize("encoding", ["msgpack", "json"])
def test_menu_task_progress_survives_checkpoint_round_trip(encoding):
    requirements = MenuPlanningRequirements(
        category_quotas=(
            CategoryQuota(category="cold_dish", count=3),
            CategoryQuota(category="soup", count=3),
        )
    )
    plan, progress = initialize_menu_task(requirements, scenario="农村宴席")
    payload = {
        "menu_execution_plan": plan.model_dump(mode="json"),
        "menu_task_progress": progress.model_dump(mode="json"),
    }
    serializer = ContractCheckpointSerializer()
    encoded = (
        serializer.dumps_typed(payload)
        if encoding == "msgpack"
        else ("json", serializer.dumps(payload))
    )

    restored = serializer.loads_typed(encoded)

    assert restored == payload
    assert restored["menu_task_progress"]["remaining"] == {
        "cold_dish": 3,
        "soup": 3,
    }
