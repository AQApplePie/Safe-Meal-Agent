"""Agent Orchestrator 内部服务接口。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from safemeal.application.agent.request_service import (
    AgentRequestService,
)
from safemeal.interfaces.http.dependencies import (
    get_agent_request_service,
)
from safemeal.application.contracts.agent import (
    AgentProcessRequest,
    AgentProcessResponse,
)
from safemeal.config.settings import settings
from safemeal.interfaces.http.answer_stream import stream_answer_events
from safemeal.shared.types import JsonObject

router = APIRouter()


@router.post("/process", response_model=AgentProcessResponse)
async def process_agent_request(
    request: AgentProcessRequest,
    request_service: AgentRequestService = Depends(get_agent_request_service),
) -> AgentProcessResponse:
    """执行一次Agent请求，供受信任内部服务调用。

    该接口不会写入chat_messages，适用于无需会话持久化的内部调用。
    """

    return await request_service.handle(request)


@router.post("/process-stream")
async def process_agent_request_stream(
    request: AgentProcessRequest,
    request_service: AgentRequestService = Depends(get_agent_request_service),
) -> StreamingResponse:
    """SSE response with first-answer deadline detection and graceful degradation."""

    def completed(result: AgentProcessResponse, degraded: bool) -> JsonObject:
        return {
            "status": result.status,
            "route": result.route,
            "sources": [item.model_dump(mode="json") for item in result.sources],
            "degraded": degraded,
        }

    async def events() -> AsyncIterator[str]:
        async for event in stream_answer_events(
            lambda: request_service.handle(request),
            completed_payload=completed,
            timeout_seconds=settings.STREAM_FIRST_PACKET_TIMEOUT,
            chunk_chars=settings.STREAM_CHUNK_CHARS,
        ):
            yield event

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
