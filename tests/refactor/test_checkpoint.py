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
