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
from safemeal.application.service.chat.chat_exceptions import (
    ChatAgentUnavailableError,
    ChatSessionNotFoundError,
    ChatTurnConflictError,
)
from safemeal.application.service.chat.chat_session_service import (
    ChatSessionService,
)
from safemeal.application.service.chat.chat_turn_service import ChatTurnService
from safemeal.interfaces.http.dependencies import (
    get_chat_session_service,
    get_chat_turn_service,
)
from safemeal.interfaces.http.models import ChatMessageResponse
from safemeal.interfaces.http.answer_stream import stream_answer_events
from safemeal.interfaces.http.authentication import (
    Principal,
    get_current_principal,
)
from safemeal.config.settings import settings
from safemeal.shared.types import JsonObject
from safemeal.application.contracts.chat.turn import ChatRequest, ChatResponse

from fastapi import Response
from safemeal.application.contracts.chat.messages import ChatSessionUpdate
from safemeal.interfaces.http.models import (
    ChatSessionResponse,
    ChatSessionUpdateRequest,
    UserMemoryResponse,
    UserMemoryUpdateRequest,
)
from safemeal.application.service.memory.user_memory_service import UserMemoryService
from safemeal.interfaces.http.dependencies import (
    get_user_memory_service,
    get_chat_workflow,
)
from safemeal.application.contracts.memory.models import UserMemoryUpdate
from safemeal.application.contracts.agent.api import (
    AgentResumeRequest,
    AgentProcessResponse,
)
from safemeal.application.workflow.runner import ChatWorkflow

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
        return await turn_service.handle(
            request.model_copy(update={"user_id": principal.storage_subject})
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

    bound_request = request.model_copy(
        update={"user_id": principal.storage_subject}
    )

    def completed(result: ChatResponse, degraded: bool) -> JsonObject:
        return {
            "status": "ok",
            "session_id": result.session_id,
            "message_id": result.message_id,
            "route": result.route,
            "sources": [item.model_dump(mode="json") for item in result.sources],
            "degraded": degraded or result.metadata.get("agent_status") == "degraded",
            "metadata": result.metadata,
            "recipe": result.recipe.model_dump(mode="json") if result.recipe else None,
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
    principal: Principal = Depends(get_current_principal),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> List[ChatMessageResponse]:
    """
    Get chat history for a session
    """
    user_id = principal.storage_subject
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


@router.delete("/sessions/{session_id}/messages")
async def clear_chat_session(
    session_id: str,
    session_service: ChatSessionService = Depends(get_chat_session_service),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, str]:
    """
    Clear all messages in a session
    """

    user_id = principal.storage_subject
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


def _session_not_found() -> HTTPException:
    # Missing and foreign-owned sessions intentionally have identical responses.
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Session not found",
    )


@router.get("/sessions", response_model=List[ChatSessionResponse])
def list_chat_sessions(
    *,
    session_service: ChatSessionService = Depends(get_chat_session_service),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    active_only: bool = True,
    principal: Principal = Depends(get_current_principal),
) -> List[ChatSessionResponse]:
    """List only sessions owned by ``user_id``."""

    user_id = principal.storage_subject
    return [
        ChatSessionResponse.model_validate(item)
        for item in session_service.list_sessions(
            user_id=user_id,
            skip=skip,
            limit=limit,
            active_only=active_only,
        )
    ]


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
def get_chat_session(
    *,
    session_service: ChatSessionService = Depends(get_chat_session_service),
    session_id: str,
    principal: Principal = Depends(get_current_principal),
) -> ChatSessionResponse:
    user_id = principal.storage_subject
    session = session_service.get_session(session_id, user_id=user_id)
    if session is None:
        raise _session_not_found()
    return ChatSessionResponse.model_validate(session)


@router.patch("/sessions/{session_id}", response_model=ChatSessionResponse)
def update_chat_session(
    *,
    session_service: ChatSessionService = Depends(get_chat_session_service),
    session_id: str,
    session_update: ChatSessionUpdateRequest,
    principal: Principal = Depends(get_current_principal),
) -> ChatSessionResponse:
    user_id = principal.storage_subject
    session = session_service.update_session(
        session_id,
        user_id=user_id,
        data=ChatSessionUpdate(**session_update.model_dump(exclude_unset=True)),
    )
    if session is None:
        raise _session_not_found()
    return ChatSessionResponse.model_validate(session)


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_chat_session(
    *,
    session_service: ChatSessionService = Depends(get_chat_session_service),
    session_id: str,
    principal: Principal = Depends(get_current_principal),
) -> Response:
    user_id = principal.storage_subject
    if session_service.delete_session(session_id, user_id=user_id) is None:
        raise _session_not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/memories", response_model=List[UserMemoryResponse])
async def list_user_memories(
    include_archived: bool = Query(False, description="是否包含已归档记忆。"),
    limit: int = Query(100, ge=1, le=500),
    memory_service: UserMemoryService = Depends(get_user_memory_service),
    principal: Principal = Depends(get_current_principal),
) -> List[UserMemoryResponse]:
    """列出某个用户的长期记忆。"""

    user_id = principal.storage_subject
    records = await run_in_threadpool(
        memory_service.list_memories,
        user_id=user_id,
        include_archived=include_archived,
        limit=limit,
    )
    return [UserMemoryResponse.model_validate(item) for item in records]


@router.patch("/memories/{memory_id}", response_model=UserMemoryResponse)
async def update_user_memory(
    memory_id: int,
    request: UserMemoryUpdateRequest,
    memory_service: UserMemoryService = Depends(get_user_memory_service),
    principal: Principal = Depends(get_current_principal),
) -> UserMemoryResponse:
    """更新一条长期记忆。"""

    user_id = principal.storage_subject
    updated = await run_in_threadpool(
        memory_service.update_memory,
        memory_id,
        user_id,
        UserMemoryUpdate(**request.model_dump(exclude_unset=True)),
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found",
        )
    return UserMemoryResponse.model_validate(updated)


@router.delete("/memories/{memory_id}", response_model=UserMemoryResponse)
async def archive_user_memory(
    memory_id: int,
    memory_service: UserMemoryService = Depends(get_user_memory_service),
    principal: Principal = Depends(get_current_principal),
) -> UserMemoryResponse:
    """软删除一条长期记忆。"""

    user_id = principal.storage_subject
    archived = await run_in_threadpool(
        memory_service.archive_memory, memory_id, user_id
    )
    if archived is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found",
        )
    return UserMemoryResponse.model_validate(archived)


@router.post("/resume", response_model=AgentProcessResponse)
async def resume_chat(
    request: AgentResumeRequest,
    principal: Principal = Depends(get_current_principal),
    session_service: ChatSessionService = Depends(get_chat_session_service),
    workflow: ChatWorkflow = Depends(get_chat_workflow),
) -> AgentProcessResponse:
    user_id = principal.storage_subject
    session = await run_in_threadpool(
        session_service.get_session, request.session_id, user_id=user_id
    )
    if session is None:
        raise _session_not_found()
    return await workflow.resume(request.session_id, approved=request.approved)


__all__ = ["router"]
