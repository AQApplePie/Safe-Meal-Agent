"""SQLAlchemy chat repositories and their explicit Unit of Work."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from types import TracebackType
from typing import List, Optional, cast

from sqlalchemy import desc, select, update
from sqlalchemy.orm import Query, Session

from SafeMealAgent.back.application.contracts.chat import (
    ChatMessageCreate,
    ChatMessageUpdate,
    ChatSessionCreate,
    ChatSessionUpdate,
)
from SafeMealAgent.back.application.ports.chat_repository import ChatUnitOfWork
from SafeMealAgent.back.infrastructure.persistence.database import session_scope
from SafeMealAgent.back.infrastructure.persistence.db.models import (
    ChatMessage,
    ChatSession,
)


class SqlAlchemyChatSessionRepository:
    """SQLAlchemy data access for the chat-session aggregate."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_active(self, session_id: str, *, user_id: str) -> Optional[ChatSession]:
        return self._active_query(session_id, user_id=user_id).one_or_none()

    def get_active_for_update(
        self,
        session_id: str,
        *,
        user_id: str,
    ) -> Optional[ChatSession]:
        return (
            self._active_query(session_id, user_id=user_id)
            .with_for_update()
            .one_or_none()
        )

    def create(self, data: ChatSessionCreate) -> ChatSession:
        now = datetime.now(timezone.utc)
        entity = ChatSession(
            **data.model_dump(),
            created_at=now,
            updated_at=now,
        )
        self._session.add(entity)
        self._session.flush()
        return entity

    def list_for_user(
        self,
        *,
        user_id: str,
        skip: int,
        limit: int,
        active_only: bool,
    ) -> List[ChatSession]:
        query = self._session.query(ChatSession).filter(ChatSession.user_id == user_id)
        if active_only:
            query = query.filter(ChatSession.is_active.is_(True))
        return (
            query.order_by(desc(ChatSession.updated_at), desc(ChatSession.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def update(
        self,
        session_id: str,
        *,
        user_id: str,
        data: ChatSessionUpdate,
    ) -> Optional[ChatSession]:
        entity = self.get_active_for_update(session_id, user_id=user_id)
        if entity is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(entity, field, value)
        setattr(entity, "updated_at", datetime.now(timezone.utc))
        self._session.flush()
        return entity

    def soft_delete(
        self,
        session_id: str,
        *,
        user_id: str,
    ) -> Optional[ChatSession]:
        entity = self.get_active_for_update(session_id, user_id=user_id)
        if entity is not None:
            setattr(entity, "is_active", False)
            setattr(entity, "updated_at", datetime.now(timezone.utc))
            self._session.flush()
        return entity

    def touch(self, session_id: str, *, user_id: str) -> Optional[ChatSession]:
        entity = self.get_active(session_id, user_id=user_id)
        if entity is not None:
            setattr(entity, "updated_at", datetime.now(timezone.utc))
            self._session.flush()
        return entity

    def count_for_user(self, user_id: str) -> int:
        return (
            self._session.query(ChatSession)
            .filter(ChatSession.user_id == user_id)
            .count()
        )

    def _active_query(self, session_id: str, *, user_id: str) -> Query[ChatSession]:
        return self._session.query(ChatSession).filter(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
            ChatSession.is_active.is_(True),
        )


class SqlAlchemyChatMessageRepository:
    """SQLAlchemy data access for chat messages and their order allocator."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def reserve_orders(
        self,
        session_id: str,
        *,
        user_id: str,
        count: int,
    ) -> Optional[int]:
        """Atomically reserve a contiguous message-order range."""

        if count <= 0:
            raise ValueError("count must be positive")

        statement = (
            update(ChatSession)
            .where(
                ChatSession.id == session_id,
                ChatSession.user_id == user_id,
                ChatSession.is_active.is_(True),
            )
            .values(
                next_message_order=ChatSession.next_message_order + count,
                updated_at=datetime.now(timezone.utc),
            )
        )
        result = self._session.execute(statement)
        if result.rowcount != 1:
            return None

        next_order = self._session.execute(
            select(ChatSession.next_message_order).where(
                ChatSession.id == session_id,
                ChatSession.user_id == user_id,
            )
        ).scalar_one()
        return int(next_order) - count

    def create(self, data: ChatMessageCreate) -> ChatMessage:
        entity = ChatMessage(**data.model_dump())
        self._session.add(entity)
        self._session.flush()
        return entity

    def update(
        self,
        message_id: int,
        data: ChatMessageUpdate,
    ) -> Optional[ChatMessage]:
        entity = self._session.get(ChatMessage, message_id)
        if entity is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(entity, field, value)
        setattr(entity, "updated_at", datetime.now(timezone.utc))
        self._session.flush()
        return entity

    def get(self, message_id: int, *, user_id: str) -> Optional[ChatMessage]:
        return (
            self._session.query(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .filter(
                ChatMessage.id == message_id,
                ChatSession.user_id == user_id,
                ChatSession.is_active.is_(True),
            )
            .one_or_none()
        )

    def get_by_request_id(
        self,
        session_id: str,
        *,
        user_id: str,
        request_id: str,
    ) -> Optional[ChatMessage]:
        return (
            self._session.query(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .filter(
                ChatMessage.session_id == session_id,
                ChatMessage.client_request_id == request_id,
                ChatSession.user_id == user_id,
                ChatSession.is_active.is_(True),
            )
            .one_or_none()
        )

    def get_response_for(
        self, message_id: int, *, user_id: str
    ) -> Optional[ChatMessage]:
        return (
            self._session.query(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .filter(
                ChatMessage.reply_to_message_id == message_id,
                ChatSession.user_id == user_id,
                ChatSession.is_active.is_(True),
            )
            .one_or_none()
        )

    def list_for_session(
        self,
        session_id: str,
        *,
        user_id: str,
        offset: int,
        limit: int,
    ) -> List[ChatMessage]:
        return (
            self._session.query(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .filter(
                ChatMessage.session_id == session_id,
                ChatSession.user_id == user_id,
                ChatSession.is_active.is_(True),
            )
            .order_by(ChatMessage.order_index)
            .offset(offset)
            .limit(limit)
            .all()
        )

    def recent_for_session(
        self,
        session_id: str,
        *,
        user_id: str,
        limit: int,
        before_order_index: Optional[int] = None,
    ) -> List[ChatMessage]:
        if limit <= 0:
            return []
        query = (
            self._session.query(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .filter(
                ChatMessage.session_id == session_id,
                ChatSession.user_id == user_id,
                ChatSession.is_active.is_(True),
                ChatMessage.message_type.in_(("user_query", "agent_response")),
            )
        )
        if before_order_index is not None:
            query = query.filter(ChatMessage.order_index < before_order_index)
        records = query.order_by(desc(ChatMessage.order_index)).limit(limit).all()
        return list(reversed(records))

    def previous_user_message(
        self,
        session_id: str,
        *,
        user_id: str,
        before_order_index: int,
    ) -> Optional[ChatMessage]:
        return (
            self._session.query(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .filter(
                ChatMessage.session_id == session_id,
                ChatMessage.message_type == "user_query",
                ChatMessage.order_index < before_order_index,
                ChatSession.user_id == user_id,
                ChatSession.is_active.is_(True),
            )
            .order_by(desc(ChatMessage.order_index))
            .first()
        )

    def delete_for_session(self, session_id: str) -> int:
        return int(
            self._session.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .delete(synchronize_session=False)
            or 0
        )


class SqlAlchemyChatUnitOfWork:
    """Own one Session and coordinate all chat repositories in one transaction."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._scope: AbstractContextManager[Session] | None = None
        self._session: Session | None = None
        self._sessions: SqlAlchemyChatSessionRepository | None = None
        self._messages: SqlAlchemyChatMessageRepository | None = None

    @property
    def sessions(self) -> SqlAlchemyChatSessionRepository:
        if self._sessions is None:
            raise RuntimeError("chat Unit of Work is not active")
        return self._sessions

    @property
    def messages(self) -> SqlAlchemyChatMessageRepository:
        if self._messages is None:
            raise RuntimeError("chat Unit of Work is not active")
        return self._messages

    def __enter__(self) -> "SqlAlchemyChatUnitOfWork":
        if self._scope is not None:
            raise RuntimeError("chat Unit of Work cannot be re-entered")
        scope = session_scope(commit=False, session_factory=self._session_factory)
        session = scope.__enter__()
        self._scope = scope
        self._session = session
        self._sessions = SqlAlchemyChatSessionRepository(session)
        self._messages = SqlAlchemyChatMessageRepository(session)
        return self

    def commit(self) -> None:
        self._require_session().commit()

    def rollback(self) -> None:
        self._require_session().rollback()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        scope = self._scope
        if scope is None:
            raise RuntimeError("chat Unit of Work is not active")
        try:
            scope.__exit__(exc_type, exc_value, traceback)
        finally:
            self._scope = None
            self._session = None
            self._sessions = None
            self._messages = None

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("chat Unit of Work is not active")
        return self._session


def sqlalchemy_chat_unit_of_work() -> ChatUnitOfWork:
    """Create a Unit of Work using the process-configured Session factory."""

    return cast(ChatUnitOfWork, SqlAlchemyChatUnitOfWork())


__all__ = [
    "SqlAlchemyChatMessageRepository",
    "SqlAlchemyChatSessionRepository",
    "SqlAlchemyChatUnitOfWork",
    "sqlalchemy_chat_unit_of_work",
]
