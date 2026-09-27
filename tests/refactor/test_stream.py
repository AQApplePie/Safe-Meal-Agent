import pytest
from safemeal.application.contracts.agent.api import AgentProcessResponse
from safemeal.application.contracts.chat.turn import ChatRequest, ChatTurnStart
from safemeal.application.observability.streaming import (
    emit_answer_chunk,
    suppress_answer_stream,
    emit_workflow_progress,
)
from safemeal.application.service.chat.chat_turn_service import ChatTurnService


class Workflow:
    async def run(self, request):
        await emit_workflow_progress("final_safety", "正在复核食材")
        with suppress_answer_stream():
            await emit_answer_chunk("DO_NOT_PUBLISH")
        return AgentProcessResponse(
            message="审核通过的回答", metadata={"safety_review": "passed"}
        )


class Persistence:
    def __init__(self, fail=False):
        self.fail = fail
        self.saved = []
        self.failed = False

    def start_turn(self, *args, **kwargs):
        return ChatTurnStart("s", 1, 2, [])

    def save_agent_response(self, **kwargs):
        if self.fail:
            raise RuntimeError("storage unavailable")
        self.saved.append(kwargs)
        return "2"

    def mark_turn_failed(self, **kwargs):
        self.failed = True


@pytest.mark.asyncio
async def test_sse_only_publishes_the_persisted_reviewed_answer(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    from safemeal.interfaces.http.answer_stream import stream_answer_events

    persistence = Persistence()
    service = ChatTurnService(persistence=persistence, workflow=Workflow())
    events = [
        event
        async for event in stream_answer_events(
            lambda: service.handle(ChatRequest(message="推荐晚餐", user_id="u")),
            completed_payload=lambda result, degraded: {"status": "ok"},
            timeout_seconds=1,
            chunk_chars=100,
        )
    ]
    combined = "".join(events)
    assert "event: progress" in combined
    assert "DO_NOT_PUBLISH" not in combined
    assert "审核通过的回答" in combined
    assert persistence.saved[0]["response"] == "审核通过的回答"


@pytest.mark.asyncio
async def test_persistence_failure_does_not_publish_draft(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    from safemeal.interfaces.http.answer_stream import stream_answer_events

    persistence = Persistence(fail=True)
    service = ChatTurnService(persistence=persistence, workflow=Workflow())
    events = [
        event
        async for event in stream_answer_events(
            lambda: service.handle(ChatRequest(message="推荐晚餐", user_id="u")),
            completed_payload=lambda result, degraded: {"status": "ok"},
            timeout_seconds=1,
            chunk_chars=100,
        )
    ]
    combined = "".join(events)
    assert "event: error" in combined
    assert "event: answer" not in combined
    assert persistence.failed
