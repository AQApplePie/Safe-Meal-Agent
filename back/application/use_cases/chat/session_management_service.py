"""User-scoped session and history management use cases."""

from __future__ import annotations

from typing import Optional

from SafeMealAgent.back.application.contracts.chat import (
    ChatSessionCreate,
    ChatSessionUpdate,
)
from SafeMealAgent.back.application.ports.chat_repository import (
    ChatMessageRecord,
    ChatSessionRecord,
    ChatUnitOfWork,
    ChatUnitOfWorkFactory,
)
from SafeMealAgent.back.application.use_cases.chat.errors import ChatSessionNotFoundError


class SessionManagementService:
    """Manage sessions through one explicit Unit of Work per use case."""

    def __init__(self, uow_factory: ChatUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def list_sessions(
        self,
        *,
        user_id: str,
        skip: int,
        limit: int,
        active_only: bool,
    ) -> list[ChatSessionRecord]:
        with self._uow_factory() as uow:
            return uow.sessions.list_for_user(
                user_id=user_id,
                skip=skip,
                limit=limit,
                active_only=active_only,
            )

    def create_session(self, data: ChatSessionCreate) -> ChatSessionRecord:
        with self._uow_factory() as uow:
            session = uow.sessions.create(data)
            uow.commit()
            return session

    def get_session(
        self,
        session_id: str,
        *,
        user_id: str,
    ) -> Optional[ChatSessionRecord]:
        with self._uow_factory() as uow:
            return uow.sessions.get_active(session_id, user_id=user_id)

    def update_session(
        self,
        session_id: str,
        *,
        user_id: str,
        data: ChatSessionUpdate,
    ) -> Optional[ChatSessionRecord]:
        with self._uow_factory() as uow:
            session = uow.sessions.update(session_id, user_id=user_id, data=data)
            if session is not None:
                uow.commit()
            return session

    def delete_session(
        self,
        session_id: str,
        *,
        user_id: str,
    ) -> Optional[ChatSessionRecord]:
        with self._uow_factory() as uow:
            session = uow.sessions.soft_delete(session_id, user_id=user_id)
            if session is not None:
                uow.commit()
            return session

    def count_sessions(self, user_id: str) -> int:
        with self._uow_factory() as uow:
            return uow.sessions.count_for_user(user_id)

    def list_messages(
        self,
        session_id: str,
        *,
        user_id: str,
        offset: int,
        limit: int,
    ) -> list[ChatMessageRecord]:
        with self._uow_factory() as uow:
            self._require_session(uow, session_id, user_id=user_id)
            return uow.messages.list_for_session(
                session_id,
                user_id=user_id,
                offset=offset,
                limit=limit,
            )

    def get_message(
        self,
        message_id: int,
        *,
        user_id: str,
    ) -> Optional[ChatMessageRecord]:
        with self._uow_factory() as uow:
            return uow.messages.get(message_id, user_id=user_id)

    def get_question_before_message(
        self,
        message: ChatMessageRecord,
        *,
        user_id: str,
    ) -> Optional[str]:
        with self._uow_factory() as uow:
            previous = uow.messages.previous_user_message(
                message.session_id,
                user_id=user_id,
                before_order_index=message.order_index,
            )
            return previous.content if previous is not None else None

    def clear_messages(self, session_id: str, *, user_id: str) -> int:
        with self._uow_factory() as uow:
            self._require_session_for_update(uow, session_id, user_id=user_id)
            deleted = uow.messages.delete_for_session(session_id)
            uow.commit()
            return deleted

    @staticmethod
    def _require_session(
        uow: ChatUnitOfWork,
        session_id: str,
        *,
        user_id: str,
    ) -> ChatSessionRecord:
        session = uow.sessions.get_active(session_id, user_id=user_id)
        if session is None:
            raise ChatSessionNotFoundError()
        return session

    @staticmethod
    def _require_session_for_update(
        uow: ChatUnitOfWork,
        session_id: str,
        *,
        user_id: str,
    ) -> ChatSessionRecord:
        session = uow.sessions.get_active_for_update(session_id, user_id=user_id)
        if session is None:
            raise ChatSessionNotFoundError()
        return session
