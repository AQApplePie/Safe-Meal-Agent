"""定义应用层依赖的能力端口。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from types import TracebackType
from typing import List, Optional, Protocol, TypeAlias

from safemeal.application.contracts.chat.messages import (
    ChatMessageCreate,
    ChatMessageUpdate,
    ChatSessionCreate,
    ChatSessionUpdate,
)
from safemeal.shared.types import JsonObject


class ChatSessionRecord(Protocol):

    id: str
    title: str
    user_id: str
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]


class ChatMessageRecord(Protocol):

    id: int
    session_id: str
    message_type: str
    content: str
    message_metadata: Optional[JsonObject]
    order_index: int
    client_request_id: Optional[str]
    reply_to_message_id: Optional[int]
    turn_status: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]


class ChatSessionRepository(Protocol):

    def get_active(
        self,
        session_id: str,
        *,
        user_id: str,
    ) -> Optional[ChatSessionRecord]: ...

    def create(self, data: ChatSessionCreate) -> ChatSessionRecord: ...

    def list_for_user(
        self,
        *,
        user_id: str,
        skip: int,
        limit: int,
        active_only: bool,
    ) -> List[ChatSessionRecord]: ...

    def update(
        self,
        session_id: str,
        *,
        user_id: str,
        data: ChatSessionUpdate,
    ) -> Optional[ChatSessionRecord]: ...

    def soft_delete(
        self,
        session_id: str,
        *,
        user_id: str,
    ) -> Optional[ChatSessionRecord]: ...

    def touch(
        self,
        session_id: str,
        *,
        user_id: str,
    ) -> Optional[ChatSessionRecord]: ...

    def count_for_user(self, user_id: str) -> int: ...


class ChatMessageRepository(Protocol):

    def next_order(
        self,
        session_id: str,
        *,
        user_id: str,
    ) -> Optional[int]: ...

    def create(self, data: ChatMessageCreate) -> ChatMessageRecord: ...

    def update(
        self,
        message_id: int,
        data: ChatMessageUpdate,
    ) -> Optional[ChatMessageRecord]: ...

    def get(
        self,
        message_id: int,
        *,
        user_id: str,
    ) -> Optional[ChatMessageRecord]: ...

    def list_for_session(
        self,
        session_id: str,
        *,
        user_id: str,
        offset: int,
        limit: int,
    ) -> List[ChatMessageRecord]: ...

    def recent_for_session(
        self,
        session_id: str,
        *,
        user_id: str,
        limit: int,
        before_order_index: Optional[int] = None,
    ) -> List[ChatMessageRecord]: ...

    def previous_user_message(
        self,
        session_id: str,
        *,
        user_id: str,
        before_order_index: int,
    ) -> Optional[ChatMessageRecord]: ...

    def delete_for_session(self, session_id: str) -> int: ...


class ChatUnitOfWork(Protocol):

    @property
    def sessions(self) -> ChatSessionRepository: ...

    @property
    def messages(self) -> ChatMessageRepository: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def __enter__(self) -> "ChatUnitOfWork": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


ChatUnitOfWorkFactory: TypeAlias = Callable[[], ChatUnitOfWork]


__all__ = [
    "ChatMessageRecord",
    "ChatMessageRepository",
    "ChatSessionRecord",
    "ChatSessionRepository",
    "ChatUnitOfWork",
    "ChatUnitOfWorkFactory",
]
