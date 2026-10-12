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
from safemeal.modules.conversation.application.chat_exceptions import (
    ChatAgentUnavailableError,
    ChatSessionNotFoundError,
    ChatTurnConflictError,
)
from safemeal.modules.conversation.application.chat_session_service import (
    ChatSessionService,
)
from safemeal.agent.gateway.chat_turn_service import ChatTurnService
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
from safemeal.modules.conversation.contracts.chat.turn import ChatRequest, ChatResponse

from fastapi import Response
from safemeal.modules.conversation.contracts.chat.messages import ChatSessionUpdate
from safemeal.interfaces.http.models import (
    ChatSessionResponse,
    ChatSessionUpdateRequest,
    UserMemoryResponse,
    UserMemoryUpdateRequest,
)
from safemeal.modules.conversation.application.memory.user_memory_service import (
    UserMemoryService,
)
from safemeal.interfaces.http.dependencies import (
    get_user_memory_service,
)
from safemeal.modules.conversation.contracts.memory.models import UserMemoryUpdate
from safemeal.agent.contracts.api import (
    AgentResumeRequest,
    AgentProcessResponse,
)

from safemeal.agent.runtime.tools.knowledge_scope import knowledge_scope

router = APIRouter()


# 方法说明：create_chat_turn
# 作用：接收用户聊天请求并执行统一聊天用例。
# 入参：
#   request（ChatRequest）：用户聊天请求。
#   turn_service（ChatTurnService）：聊天轮次与审批恢复业务服务；由 FastAPI 依赖注入。
#   principal（Principal）：通过认证后建立的可信身份主体；由 FastAPI 依赖注入。
# 出参：ChatResponse；用户聊天响应。
@router.post("/", response_model=ChatResponse)
async def create_chat_turn(
    request: ChatRequest,
    turn_service: ChatTurnService = Depends(get_chat_turn_service),
    principal: Principal = Depends(get_current_principal),
) -> ChatResponse:
    try:
        with knowledge_scope(principal.tenant_id):
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


# 方法说明：stream_chat_turn
# 作用：执行聊天请求并以 SSE 输出进度和安全复核后的回复。
# 入参：
#   request（ChatRequest）：用户聊天请求。
#   turn_service（ChatTurnService）：聊天轮次与审批恢复业务服务；由 FastAPI 依赖注入。
#   principal（Principal）：通过认证后建立的可信身份主体；由 FastAPI 依赖注入。
# 出参：StreamingResponse；流式 HTTP 响应。
@router.post("/stream")
async def stream_chat_turn(
    request: ChatRequest,
    turn_service: ChatTurnService = Depends(get_chat_turn_service),
    principal: Principal = Depends(get_current_principal),
) -> StreamingResponse:

    bound_request = request.model_copy(update={"user_id": principal.storage_subject})

    # 方法说明：completed
    # 作用：判断当前菜单任务是否满足全部必需分类配额。
    # 入参：
    #   result（ChatResponse）：用户聊天响应。
    #   degraded（bool）：是否处于依赖降级状态。
    # 出参：JsonObject；全部菜单分类配额是否已满足。
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

    # 方法说明：events
    # 作用：将本轮聊天进度、答案及错误转换成 SSE 事件序列。
    # 入参：
    #   无显式入参。
    # 出参：AsyncIterator[str]；可逐条发送的 SSE 事件异步迭代器。
    async def events() -> AsyncIterator[str]:
        with knowledge_scope(principal.tenant_id):
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


# 方法说明：get_chat_history
# 作用：读取当前用户拥有会话的历史消息。
# 入参：
#   session_id（str）：聊天会话或图检查点线程标识。
#   session_service（ChatSessionService）：聊天会话业务服务；由 FastAPI 依赖注入。
#   principal（Principal）：通过认证后建立的可信身份主体；由 FastAPI 依赖注入。
#   limit（int）：本次查询或处理的最大条目数；默认值为 Query(50, ge=1, le=100)。
#   offset（int）：本次分页跳过的记录数量；默认值为 Query(0, ge=0)。
# 出参：List[ChatMessageResponse]；聊天消息 HTTP 响应的集合。
@router.get("/history/{session_id}", response_model=List[ChatMessageResponse])
async def get_chat_history(
    session_id: str,
    session_service: ChatSessionService = Depends(get_chat_session_service),
    principal: Principal = Depends(get_current_principal),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> List[ChatMessageResponse]:
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


# 方法说明：clear_chat_session
# 作用：清空当前用户拥有会话的消息。
# 入参：
#   session_id（str）：聊天会话或图检查点线程标识。
#   session_service（ChatSessionService）：聊天会话业务服务；由 FastAPI 依赖注入。
#   principal（Principal）：通过认证后建立的可信身份主体；由 FastAPI 依赖注入。
# 出参：dict[str, str]；会话消息清理成功的状态响应。
@router.delete("/sessions/{session_id}/messages")
async def clear_chat_session(
    session_id: str,
    session_service: ChatSessionService = Depends(get_chat_session_service),
    principal: Principal = Depends(get_current_principal),
) -> dict[str, str]:

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

    try:
        await run_in_threadpool(
            session_service.clear_messages,
            session_id,
            user_id=user_id,
        )
    except ChatTurnConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {"message": "Session cleared successfully", "session_id": session_id}


# 方法说明：_session_not_found
# 作用：构造会话不存在或不可访问时的稳定错误响应。
# 入参：
#   无显式入参。
# 出参：HTTPException；HTTP 异常对象。
def _session_not_found() -> HTTPException:

    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Session not found",
    )


# 方法说明：list_chat_sessions
# 作用：分页返回当前用户拥有的聊天会话。
# 入参：
#   session_service（ChatSessionService）：聊天会话业务服务；由 FastAPI 依赖注入。
#   skip（int）：本次分页跳过的记录数量；默认值为 Query(default=0, ge=0)。
#   limit（int）：本次查询或处理的最大条目数；默认值为 Query(default=50, ge=1, le=100)。
#   active_only（bool）：是否仅查询活动记录；默认值为 True。
#   principal（Principal）：通过认证后建立的可信身份主体；由 FastAPI 依赖注入。
# 出参：List[ChatSessionResponse]；聊天会话 HTTP 响应的集合。
@router.get("/sessions", response_model=List[ChatSessionResponse])
def list_chat_sessions(
    *,
    session_service: ChatSessionService = Depends(get_chat_session_service),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    active_only: bool = True,
    principal: Principal = Depends(get_current_principal),
) -> List[ChatSessionResponse]:

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


# 方法说明：get_chat_session
# 作用：查询当前用户拥有的指定聊天会话。
# 入参：
#   session_service（ChatSessionService）：聊天会话业务服务；由 FastAPI 依赖注入。
#   session_id（str）：聊天会话或图检查点线程标识。
#   principal（Principal）：通过认证后建立的可信身份主体；由 FastAPI 依赖注入。
# 出参：ChatSessionResponse；聊天会话 HTTP 响应。
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


# 方法说明：update_chat_session
# 作用：更新当前用户拥有会话的可修改字段。
# 入参：
#   session_service（ChatSessionService）：聊天会话业务服务；由 FastAPI 依赖注入。
#   session_id（str）：聊天会话或图检查点线程标识。
#   session_update（ChatSessionUpdateRequest）：仅包含会话可修改字段的更新命令。
#   principal（Principal）：通过认证后建立的可信身份主体；由 FastAPI 依赖注入。
# 出参：ChatSessionResponse；聊天会话 HTTP 响应。
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


# 方法说明：delete_chat_session
# 作用：删除用户拥有的会话及其相关消息。
# 入参：
#   session_service（ChatSessionService）：聊天会话业务服务；由 FastAPI 依赖注入。
#   session_id（str）：聊天会话或图检查点线程标识。
#   principal（Principal）：通过认证后建立的可信身份主体；由 FastAPI 依赖注入。
# 出参：Response；HTTP 响应。
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


# 方法说明：list_user_memories
# 作用：列出某个用户的长期记忆。
# 入参：
#   include_archived（bool）：是否包含归档记忆；默认值为 Query(False,
# description='是否包含已归档记忆。')。
#   limit（int）：本次查询或处理的最大条目数；默认值为 Query(100, ge=1, le=500)。
#   memory_service（UserMemoryService）：长期记忆业务服务；由 FastAPI 依赖注入。
#   principal（Principal）：通过认证后建立的可信身份主体；由 FastAPI 依赖注入。
# 出参：List[UserMemoryResponse]；长期记忆 HTTP 响应的集合。
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


# 方法说明：update_user_memory
# 作用：更新一条长期记忆。
# 入参：
#   memory_id（int）：长期记忆标识。
#   request（UserMemoryUpdateRequest）：长期记忆 HTTP 更新请求。
#   memory_service（UserMemoryService）：长期记忆业务服务；由 FastAPI 依赖注入。
#   principal（Principal）：通过认证后建立的可信身份主体；由 FastAPI 依赖注入。
# 出参：UserMemoryResponse；长期记忆 HTTP 响应。
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


# 方法说明：archive_user_memory
# 作用：软删除一条长期记忆。
# 入参：
#   memory_id（int）：长期记忆标识。
#   memory_service（UserMemoryService）：长期记忆业务服务；由 FastAPI 依赖注入。
#   principal（Principal）：通过认证后建立的可信身份主体；由 FastAPI 依赖注入。
# 出参：UserMemoryResponse；长期记忆 HTTP 响应。
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


# 方法说明：resume_chat
# 作用：校验审批恢复请求并通过聊天用例继续已暂停任务。
# 入参：
#   request（AgentResumeRequest）：Agent 审批恢复请求。
#   principal（Principal）：通过认证后建立的可信身份主体；由 FastAPI 依赖注入。
#   turn_service（ChatTurnService）：聊天轮次与审批恢复业务服务；由 FastAPI 依赖注入。
# 出参：AgentProcessResponse；Agent 内部处理响应。
@router.post("/resume", response_model=AgentProcessResponse)
async def resume_chat(
    request: AgentResumeRequest,
    principal: Principal = Depends(get_current_principal),
    turn_service: ChatTurnService = Depends(get_chat_turn_service),
) -> AgentProcessResponse:
    try:
        with knowledge_scope(principal.tenant_id):
            return await turn_service.resume(request, user_id=principal.storage_subject)
    except ChatSessionNotFoundError as exc:
        raise _session_not_found() from exc
    except ChatTurnConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


__all__ = ["router"]
