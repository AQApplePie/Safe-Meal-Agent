from __future__ import annotations

import asyncio

from SafeMealAgent.back.application.observability import emit_answer_chunk
from SafeMealAgent.back.application.use_cases.chat.errors import ChatAgentUnavailableError
from SafeMealAgent.back.interfaces.http.answer_stream import stream_answer_events
from SafeMealAgent.back.interfaces.http.security import Principal
from SafeMealAgent.back.interfaces.http.v1.endpoints.chat import chat_stream
from SafeMealAgent.back.shared.contracts.chat import ChatRequest, ChatResponse


async def _collect(iterator) -> str:
    return "".join([item async for item in iterator])


def test_first_packet_timeout_emits_degraded_then_final_answer() -> None:
    class SlowResponse:
        message = "最终答案"

    async def operation() -> SlowResponse:
        await asyncio.sleep(0.02)
        return SlowResponse()

    async def scenario() -> str:
        return await _collect(
            stream_answer_events(
                operation,
                completed_payload=lambda result, degraded: {
                    "status": "ok",
                    "degraded": degraded,
                },
                timeout_seconds=0.001,
                chunk_chars=2,
            )
        )

    body = asyncio.run(scenario())
    assert "event: degraded" in body
    assert "first_answer_timeout" in body
    assert body.count("event: answer") == 2
    assert '"degraded": true' in body


def test_stream_failure_is_an_sse_error_and_preserves_partial_flag() -> None:
    async def operation():
        await emit_answer_chunk("已经发送")
        raise ChatAgentUnavailableError(error_code="model_partial_stream_interrupted")

    async def scenario() -> str:
        return await _collect(
            stream_answer_events(
                operation,
                completed_payload=lambda result, degraded: {"status": "ok"},
                timeout_seconds=1,
                chunk_chars=10,
            )
        )

    body = asyncio.run(scenario())
    assert body.count("已经发送") == 1
    assert "event: error" in body
    assert "model_partial_stream_interrupted" in body
    assert '"partial_answer": true' in body


def test_public_chat_stream_binds_identity_and_returns_completion_metadata() -> None:
    class ChatService:
        received: ChatRequest | None = None

        async def handle(self, request: ChatRequest) -> ChatResponse:
            self.received = request
            await emit_answer_chunk("公开流式答案")
            return ChatResponse(
                message="公开流式答案",
                session_id="session-1",
                message_id="message-1",
            )

    service = ChatService()
    principal = Principal(
        subject="trusted-user", roles=frozenset({"user"}), trusted=True
    )

    async def scenario() -> str:
        response = await chat_stream(
            ChatRequest(message="你好", user_id="trusted-user"),
            service,  # type: ignore[arg-type]
            principal,
        )
        return await _collect(response.body_iterator)

    body = asyncio.run(scenario())
    assert service.received is not None
    assert service.received.user_id == "trusted-user"
    assert body.count("公开流式答案") == 1
    assert '"session_id": "session-1"' in body
    assert '"message_id": "message-1"' in body
    assert "event: done" in body
