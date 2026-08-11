"""用户长期记忆 API。

Memory 是食谱 Agent 主流程的高频上下文能力，默认随主后端本地部署。
该 Router 直接调用应用层 ``UserMemoryService``，不再通过 HTTP 代理到 Memory Service。
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from starlette.concurrency import run_in_threadpool

from safemeal.application.use_cases.memory.user_memory_service import UserMemoryService
from safemeal.interfaces.http.dependencies import get_user_memory_service
from safemeal.interfaces.http.models.memory import (
    UserMemoryCreateRequest,
    UserMemoryRememberRequest,
    UserMemoryResponse,
    UserMemoryUpdateRequest,
)
from safemeal.interfaces.http.authentication import (
    Principal,
    authorize_user_id,
    get_current_principal,
)
from safemeal.shared.contracts.memory import (
    UserMemoryCreate,
    UserMemoryUpdate,
)
from safemeal.shared.types import JsonObject

router = APIRouter()


@router.get("/", response_model=List[UserMemoryResponse])
async def list_user_memories(
    user_id: str = Query(..., min_length=1, description="用户标识。"),
    include_archived: bool = Query(False, description="是否包含已归档记忆。"),
    limit: int = Query(100, ge=1, le=500),
    memory_service: UserMemoryService = Depends(get_user_memory_service),
    principal: Principal = Depends(get_current_principal),
) -> List[UserMemoryResponse]:
    """列出某个用户的长期记忆。"""

    user_id = authorize_user_id(principal, user_id)
    records = await run_in_threadpool(
        memory_service.list_memories,
        user_id=user_id,
        include_archived=include_archived,
        limit=limit,
    )
    return [UserMemoryResponse.model_validate(item) for item in records]


@router.get("/agent-context", response_model=List[dict])
async def load_agent_memory_context(
    user_id: str = Query(..., min_length=1, description="用户标识。"),
    limit: int = Query(50, ge=1, le=200),
    memory_service: UserMemoryService = Depends(get_user_memory_service),
    principal: Principal = Depends(get_current_principal),
) -> List[JsonObject]:
    """返回 Agent 可直接注入的长期记忆上下文。"""

    user_id = authorize_user_id(principal, user_id)
    return await run_in_threadpool(
        memory_service.load_agent_memories,
        user_id=user_id,
        limit=limit,
    )


@router.post(
    "/", response_model=UserMemoryResponse, status_code=status.HTTP_201_CREATED
)
async def create_user_memory(
    request: UserMemoryCreateRequest,
    memory_service: UserMemoryService = Depends(get_user_memory_service),
    principal: Principal = Depends(get_current_principal),
) -> UserMemoryResponse:
    """手动创建或刷新一条长期记忆。"""

    user_id = authorize_user_id(principal, request.user_id)
    data = UserMemoryCreate(
        **request.model_dump(exclude={"user_id"}), user_id=user_id, source="manual"
    )
    record = await run_in_threadpool(memory_service.create_memory, data)
    return UserMemoryResponse.model_validate(record)


@router.post("/remember", response_model=List[UserMemoryResponse])
async def remember_from_message(
    request: UserMemoryRememberRequest,
    memory_service: UserMemoryService = Depends(get_user_memory_service),
    principal: Principal = Depends(get_current_principal),
) -> List[UserMemoryResponse]:
    """从用户消息中抽取并保存长期记忆。"""

    user_id = authorize_user_id(principal, request.user_id)
    records = await run_in_threadpool(
        memory_service.remember_from_message,
        user_id=user_id,
        message=request.message,
        source_session_id=request.source_session_id,
        source_message_id=request.source_message_id,
    )
    return [UserMemoryResponse.model_validate(item) for item in records]


@router.patch("/{memory_id}", response_model=UserMemoryResponse)
async def update_user_memory(
    memory_id: int,
    request: UserMemoryUpdateRequest,
    user_id: str = Query(..., min_length=1, max_length=255),
    memory_service: UserMemoryService = Depends(get_user_memory_service),
    principal: Principal = Depends(get_current_principal),
) -> UserMemoryResponse:
    """更新一条长期记忆。"""

    user_id = authorize_user_id(principal, user_id)
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


@router.delete("/{memory_id}", response_model=UserMemoryResponse)
async def archive_user_memory(
    memory_id: int,
    user_id: str = Query(..., min_length=1, max_length=255),
    memory_service: UserMemoryService = Depends(get_user_memory_service),
    principal: Principal = Depends(get_current_principal),
) -> UserMemoryResponse:
    """软删除一条长期记忆。"""

    user_id = authorize_user_id(principal, user_id)
    archived = await run_in_threadpool(
        memory_service.archive_memory, memory_id, user_id
    )
    if archived is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found",
        )
    return UserMemoryResponse.model_validate(archived)


__all__ = [
    "archive_user_memory",
    "create_user_memory",
    "list_user_memories",
    "load_agent_memory_context",
    "remember_from_message",
    "router",
    "update_user_memory",
]
