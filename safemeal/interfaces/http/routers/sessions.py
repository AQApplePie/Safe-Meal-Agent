"""User-scoped chat session management routers."""

from __future__ import annotations

from typing import List
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from safemeal.application.contracts.chat import ChatSessionCreate, ChatSessionUpdate
from safemeal.application.use_cases.chat.chat_session_service import (
    ChatSessionService,
)
from safemeal.interfaces import get_chat_session_service
from safemeal.interfaces import (
    ChatSessionCreateRequest,
    ChatSessionResponse,
    ChatSessionUpdateRequest,
)
from safemeal.interfaces import (
    Principal,
    authorize_user_id,
    get_current_principal,
)


router = APIRouter()


def _session_not_found() -> HTTPException:
    # Missing and foreign-owned sessions intentionally have identical responses.
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Session not found",
    )


@router.get("/", response_model=List[ChatSessionResponse])
def list_chat_sessions(
    *,
    session_service: ChatSessionService = Depends(get_chat_session_service),
    user_id: str = Query(..., min_length=1, max_length=255),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    active_only: bool = True,
    principal: Principal = Depends(get_current_principal),
) -> List[ChatSessionResponse]:
    """List only sessions owned by ``user_id``."""

    user_id = authorize_user_id(principal, user_id)
    return [
        ChatSessionResponse.model_validate(item)
        for item in session_service.list_sessions(
            user_id=user_id,
            skip=skip,
            limit=limit,
            active_only=active_only,
        )
    ]


@router.post(
    "/", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED
)
def create_chat_session(
    *,
    session_service: ChatSessionService = Depends(get_chat_session_service),
    session_in: ChatSessionCreateRequest,
    principal: Principal = Depends(get_current_principal),
) -> ChatSessionResponse:
    """Create a session whose owner is immutable after creation."""

    user_id = authorize_user_id(principal, session_in.user_id)
    return ChatSessionResponse.model_validate(
        session_service.create_session(
            ChatSessionCreate(
                id=session_in.id or str(uuid4()),
                title=session_in.title,
                user_id=user_id,
            )
        )
    )


@router.get("/user/{user_id}/count", response_model=dict)
def count_user_chat_sessions(
    *,
    session_service: ChatSessionService = Depends(get_chat_session_service),
    user_id: str,
    principal: Principal = Depends(get_current_principal),
) -> dict[str, int | str]:
    user_id = authorize_user_id(principal, user_id)
    return {
        "user_id": user_id,
        "session_count": session_service.count_sessions(user_id),
    }


@router.get("/{session_id}", response_model=ChatSessionResponse)
def get_chat_session(
    *,
    session_service: ChatSessionService = Depends(get_chat_session_service),
    session_id: str,
    user_id: str = Query(..., min_length=1, max_length=255),
    principal: Principal = Depends(get_current_principal),
) -> ChatSessionResponse:
    user_id = authorize_user_id(principal, user_id)
    session = session_service.get_session(session_id, user_id=user_id)
    if session is None:
        raise _session_not_found()
    return ChatSessionResponse.model_validate(session)


@router.patch("/{session_id}", response_model=ChatSessionResponse)
def update_chat_session(
    *,
    session_service: ChatSessionService = Depends(get_chat_session_service),
    session_id: str,
    session_update: ChatSessionUpdateRequest,
    user_id: str = Query(..., min_length=1, max_length=255),
    principal: Principal = Depends(get_current_principal),
) -> ChatSessionResponse:
    user_id = authorize_user_id(principal, user_id)
    session = session_service.update_session(
        session_id,
        user_id=user_id,
        data=ChatSessionUpdate(**session_update.model_dump(exclude_unset=True)),
    )
    if session is None:
        raise _session_not_found()
    return ChatSessionResponse.model_validate(session)


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_chat_session(
    *,
    session_service: ChatSessionService = Depends(get_chat_session_service),
    session_id: str,
    user_id: str = Query(..., min_length=1, max_length=255),
    principal: Principal = Depends(get_current_principal),
) -> Response:
    user_id = authorize_user_id(principal, user_id)
    if session_service.delete_session(session_id, user_id=user_id) is None:
        raise _session_not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
