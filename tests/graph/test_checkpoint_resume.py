from __future__ import annotations

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

from safemeal.infrastructure.persistence.langgraph_checkpoint import (
    SqliteCheckpointSaver,
)


class State(TypedDict, total=False):
    approved: bool
    outcome: str


def approval(state: State) -> State:
    decision = interrupt({"kind": "human_approval", "action": "publish"})
    return {"approved": bool(decision.get("approved"))}


def finish(state: State) -> State:
    return {"outcome": "published" if state["approved"] else "rejected"}


@pytest.mark.graph
async def test_interrupt_survives_new_checkpointer_instance(tmp_path) -> None:
    path = tmp_path / "checkpoints.sqlite3"
    config = {"configurable": {"thread_id": "tenant-a:session-1"}}
    builder = StateGraph(State)
    builder.add_node("approval", approval)
    builder.add_node("finish", finish)
    builder.add_edge(START, "approval")
    builder.add_edge("approval", "finish")
    builder.add_edge("finish", END)

    first = builder.compile(checkpointer=SqliteCheckpointSaver(path))
    interrupted = await first.ainvoke({"approved": False}, config=config)
    assert interrupted == {"approved": False}
    snapshot = await first.aget_state(config)
    assert snapshot.tasks[0].interrupts[0].value["kind"] == "human_approval"

    resumed = builder.compile(checkpointer=SqliteCheckpointSaver(path))
    result = await resumed.ainvoke(Command(resume={"approved": True}), config=config)
    assert result["outcome"] == "published"
