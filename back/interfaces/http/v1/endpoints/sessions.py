"""User-scoped chat session management endpoints."""

from __future__ import annotations

from typing import List
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from SafeMealAgent.back.application.contracts.chat import ChatSessionCreate, ChatSessionUpdate
from SafeMealAgent.back.application.use_cases.chat.session_management_service import (
    SessionManagementService,
)
from SafeMealAgent.back.interfaces.http.dependencies import get_session_management
from SafeMealAgent.back.interfaces.http.models.chat_session import (
    ChatSessionCreateRequest,
    ChatSessionResponse,
    ChatSessionUpdateRequest,
)
from SafeMealAgent.back.interfaces.http.security import (
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
def get_sessions(
    *,
    session_management: SessionManagementService = Depends(get_session_management),
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
        for item in session_management.list_sessions(
            user_id=user_id,
            skip=skip,
            limit=limit,
            active_only=active_only,
        )
    ]


@router.post(
    "/", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED
)
def create_session(
    *,
    session_management: SessionManagementService = Depends(get_session_management),
    session_in: ChatSessionCreateRequest,
    principal: Principal = Depends(get_current_principal),
) -> ChatSessionResponse:
    """Create a session whose owner is immutable after creation."""

    user_id = authorize_user_id(principal, session_in.user_id)
    return ChatSessionResponse.model_validate(
        session_management.create_session(
            ChatSessionCreate(
                id=session_in.id or str(uuid4()),
                title=session_in.title,
                user_id=user_id,
            )
        )
    )


@router.get("/user/{user_id}/count", response_model=dict)
def get_user_session_count(
    *,
    session_management: SessionManagementService = Depends(get_session_management),
    user_id: str,
    principal: Principal = Depends(get_current_principal),
) -> dict[str, int | str]:
    user_id = authorize_user_id(principal, user_id)
    return {
        "user_id": user_id,
        "session_count": session_management.count_sessions(user_id),
    }


@router.get("/{session_id}", response_model=ChatSessionResponse)
def get_session(
    *,
    session_management: SessionManagementService = Depends(get_session_management),
    session_id: str,
    user_id: str = Query(..., min_length=1, max_length=255),
    principal: Principal = Depends(get_current_principal),
) -> ChatSessionResponse:
    user_id = authorize_user_id(principal, user_id)
    session = session_management.get_session(session_id, user_id=user_id)
    if session is None:
        raise _session_not_found()
    return ChatSessionResponse.model_validate(session)


@router.patch("/{session_id}", response_model=ChatSessionResponse)
def update_session(
    *,
    session_management: SessionManagementService = Depends(get_session_management),
    session_id: str,
    session_update: ChatSessionUpdateRequest,
    user_id: str = Query(..., min_length=1, max_length=255),
    principal: Principal = Depends(get_current_principal),
) -> ChatSessionResponse:
    user_id = authorize_user_id(principal, user_id)
    session = session_management.update_session(
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
def delete_session(
    *,
    session_management: SessionManagementService = Depends(get_session_management),
    session_id: str,
    user_id: str = Query(..., min_length=1, max_length=255),
    principal: Principal = Depends(get_current_principal),
) -> Response:
    user_id = authorize_user_id(principal, user_id)
    if session_management.delete_session(session_id, user_id=user_id) is None:
        raise _session_not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
