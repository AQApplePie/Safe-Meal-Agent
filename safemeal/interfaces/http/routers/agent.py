"""Agent Orchestrator 内部服务接口。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from safemeal.interfaces.http.dependencies import get_chat_workflow
from safemeal.interfaces.http.request_mapping import to_workflow_request
from fastapi.responses import StreamingResponse

from safemeal.application.workflow.runner import ChatWorkflow
from safemeal.application.contracts.agent.api import (
    AgentResumeRequest,
    AgentProcessRequest,
    AgentProcessResponse,
)
from safemeal.config.settings import settings
from safemeal.interfaces import stream_answer_events
from safemeal.shared.types import JsonObject

router = APIRouter()


@router.post("/resume", response_model=AgentProcessResponse)
async def resume_agent_request(
    request: AgentResumeRequest,
    workflow: ChatWorkflow = Depends(get_chat_workflow),
) -> AgentProcessResponse:
    """Approve or reject an interrupted high-impact tool call."""

    return await workflow.resume(request.session_id, approved=request.approved)


@router.post("/process", response_model=AgentProcessResponse)
async def process_agent_request(
    request: AgentProcessRequest,
    workflow: ChatWorkflow = Depends(get_chat_workflow),
) -> AgentProcessResponse:
    """执行一次Agent请求，供受信任内部服务调用。

    该接口不会写入chat_messages，适用于无需会话持久化的内部调用。
    """

    return await workflow.run(to_workflow_request(request))


@router.post("/process-stream")
async def process_agent_request_stream(
    request: AgentProcessRequest,
    workflow: ChatWorkflow = Depends(get_chat_workflow),
) -> StreamingResponse:
    """SSE response with first-answer deadline detection and graceful degradation."""

    def completed(result: AgentProcessResponse, degraded: bool) -> JsonObject:
        return {
            "status": result.status,
            "route": result.route,
            "sources": [item.model_dump(mode="json") for item in result.sources],
            "degraded": degraded or result.status == "degraded",
            "metadata": result.metadata,
            "recipe": result.recipe.model_dump(mode="json") if result.recipe else None,
        }

    async def events() -> AsyncIterator[str]:
        async for event in stream_answer_events(
            lambda: workflow.run(to_workflow_request(request)),
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
