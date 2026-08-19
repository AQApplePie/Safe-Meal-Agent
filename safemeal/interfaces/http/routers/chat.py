"""统一聊天 API。

该路由只负责 HTTP 协议转换：

- 接收并校验 ChatRequest；
- 调用 ChatTurnService 完成一轮聊天用例；
- 返回 ChatResponse。

会话持久化、长期记忆加载和 Agent 调用的串联顺序不再散落在 HTTP 层。
"""

from collections.abc import AsyncIterator
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from safemeal.application.use_cases.chat.chat_exceptions import (
    ChatAgentUnavailableError,
    ChatSessionNotFoundError,
    ChatTurnConflictError,
)
from safemeal.application.use_cases.chat.chat_session_service import (
    ChatSessionService,
)
from safemeal.application.use_cases.chat.chat_turn_service import ChatTurnService
from safemeal.interfaces import (
    get_chat_session_service,
    get_chat_turn_service,
)
from safemeal.interfaces import ChatMessageResponse
from safemeal.interfaces import stream_answer_events
from safemeal.interfaces import (
    Principal,
    authorize_user_id,
    get_current_principal,
)
from safemeal.config.settings import settings
from safemeal.shared.types import JsonObject
from safemeal.application.contracts.chat_turn import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/", response_model=ChatResponse)
async def create_chat_turn(
    request: ChatRequest,
    turn_service: ChatTurnService = Depends(get_chat_turn_service),
    principal: Principal = Depends(get_current_principal),
) -> ChatResponse:
    """
    Unified chat endpoint with automatic agent routing

    - Automatically routes queries to appropriate agents
    - Persists conversation history through the Chat Turn use case
    - Supports the database and retrieval tools listed by `/routes`
    """
    try:
        user_id = authorize_user_id(principal, request.user_id)
        return await turn_service.handle(
            request.model_copy(update={"user_id": user_id})
        )
    except ChatSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        ) from exc
    except ChatTurnConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ChatAgentUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Agent is temporarily unavailable",
                "error_code": exc.error_code,
            },
        ) from exc


@router.post("/stream")
async def stream_chat_turn(
    request: ChatRequest,
    turn_service: ChatTurnService = Depends(get_chat_turn_service),
    principal: Principal = Depends(get_current_principal),
) -> StreamingResponse:
    """Public SSE chat with first-answer timeout detection and durable turns."""

    user_id = authorize_user_id(principal, request.user_id)
    bound_request = request.model_copy(update={"user_id": user_id})

    def completed(result: ChatResponse, degraded: bool) -> JsonObject:
        return {
            "status": "ok",
            "session_id": result.session_id,
            "message_id": result.message_id,
            "route": result.route,
            "sources": [item.model_dump(mode="json") for item in result.sources],
            "degraded": degraded,
        }

    async def events() -> AsyncIterator[str]:
        async for event in stream_answer_events(
            lambda: turn_service.handle(bound_request),
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


@router.get("/history/{session_id}", response_model=List[ChatMessageResponse])
async def get_chat_history(
    session_id: str,
    session_service: ChatSessionService = Depends(get_chat_session_service),
    user_id: str = Query(..., min_length=1, max_length=255),
    principal: Principal = Depends(get_current_principal),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> List[ChatMessageResponse]:
    """
    Get chat history for a session
    """
    user_id = authorize_user_id(principal, user_id)
    session = await run_in_threadpool(
        session_service.get_session,
        session_id,
        user_id=user_id,
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    messages = await run_in_threadpool(
        session_service.list_messages,
        session_id,
        user_id=user_id,
        offset=offset,
        limit=limit,
    )

    return [ChatMessageResponse.model_validate(item) for item in messages]


@router.delete("/sessions/{session_id}")
async def clear_chat_session(
    session_id: str,
    session_service: ChatSessionService = Depends(get_chat_session_service),
    user_id: str = Query(..., min_length=1, max_length=255),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, str]:
    """
    Clear all messages in a session
    """

    user_id = authorize_user_id(principal, user_id)
    session = await run_in_threadpool(
        session_service.get_session,
        session_id,
        user_id=user_id,
    )
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    await run_in_threadpool(
        session_service.clear_messages,
        session_id,
        user_id=user_id,
    )

    return {"message": "Session cleared successfully", "session_id": session_id}


__all__ = ["router"]
