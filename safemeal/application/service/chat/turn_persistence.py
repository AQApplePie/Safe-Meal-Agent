"""Simple single-host persistence orchestration for one chat turn."""

from __future__ import annotations
from safemeal.application.contracts.chat.turn import ChatTurnStart

from datetime import datetime, timezone
from typing import Iterable, Optional
from uuid import uuid4

from safemeal.application.contracts.chat.messages import (
    ChatMessageCreate,
    ChatMessageUpdate,
    ChatSessionCreate,
)
from safemeal.application.ports.persistence.chat_repository import (
    ChatMessageRecord,
    ChatSessionRecord,
    ChatUnitOfWork,
    ChatUnitOfWorkFactory,
)
from safemeal.application.service.chat.chat_exceptions import (
    ChatSessionNotFoundError,
    ChatTurnConflictError,
)
from safemeal.application.contracts.conversation.models import ConversationHistory
from safemeal.shared.types import JsonObject, JsonValue, to_json_value


_GENERIC_AGENT_ERROR = "抱歉，处理您的请求时出现了错误。请稍后重试。"


class ChatTurnPersistence:
    """Append chat messages without distributed locks or replay protocols."""

    def __init__(
        self,
        uow_factory: ChatUnitOfWorkFactory,
        *,
        history_messages: int = 12,
    ) -> None:
        if history_messages < 0:
            raise ValueError("history_messages must be non-negative")
        self._uow_factory = uow_factory
        self._history_messages = history_messages

    def start_turn(
        self,
        session_id: Optional[str],
        user_id: str,
        message: str,
        *,
        request_id: Optional[str] = None,
    ) -> ChatTurnStart:
        """Create a session when needed, load history, then append the question."""

        with self._uow_factory() as uow:
            if session_id is None:
                session_id = str(uuid4())
                uow.sessions.create(
                    ChatSessionCreate(
                        id=session_id,
                        user_id=user_id,
                        title=f"Chat {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
                    )
                )
            elif uow.sessions.get_active(session_id, user_id=user_id) is None:
                raise ChatSessionNotFoundError()

            history = self._history_before(uow, session_id, user_id=user_id)
            first_order = uow.messages.next_order(session_id, user_id=user_id)
            if first_order is None:
                raise ChatSessionNotFoundError()
            created = uow.messages.create(
                ChatMessageCreate(
                    session_id=session_id,
                    message_type="user_query",
                    content=message,
                    order_index=first_order,
                    client_request_id=request_id,
                    turn_status="processing",
                )
            )
            uow.commit()

        return ChatTurnStart(
            session_id=session_id,
            user_message_id=created.id,
            response_order_index=first_order + 1,
            history=history,
        )

    def save_agent_response(
        self,
        *,
        session_id: str,
        user_id: str,
        user_message_id: int,
        response_order_index: int,
        response: str,
        route: Optional[str] = None,
        route_logic: Optional[str] = None,
        sources: Iterable[object] = (),
        metadata: Optional[JsonObject] = None,
    ) -> str:
        response_metadata = {
            **(metadata or {}),
            "route": route,
            "route_logic": route_logic,
            "sources": [self._json_value(source) for source in sources],
        }
        with self._uow_factory() as uow:
            self._require_owned_session(uow, session_id, user_id=user_id)
            user_message = self._require_user_message(
                uow, user_message_id, session_id=session_id, user_id=user_id
            )
            created = uow.messages.create(
                ChatMessageCreate(
                    session_id=session_id,
                    message_type="agent_response",
                    content=response,
                    message_metadata=response_metadata,
                    order_index=response_order_index,
                    reply_to_message_id=user_message_id,
                )
            )
            uow.messages.update(
                user_message.id, ChatMessageUpdate(turn_status="completed")
            )
            uow.sessions.touch(session_id, user_id=user_id)
            uow.commit()
        return str(created.id)

    def save_agent_error(
        self,
        *,
        session_id: str,
        user_id: str,
        user_message_id: int,
        response_order_index: int,
        error_code: Optional[str],
    ) -> str:
        with self._uow_factory() as uow:
            self._require_owned_session(uow, session_id, user_id=user_id)
            user_message = self._require_user_message(
                uow, user_message_id, session_id=session_id, user_id=user_id
            )
            created = uow.messages.create(
                ChatMessageCreate(
                    session_id=session_id,
                    message_type="error",
                    content=_GENERIC_AGENT_ERROR,
                    message_metadata={
                        "error_code": error_code or "agent_execution_failed"
                    },
                    order_index=response_order_index,
                    reply_to_message_id=user_message_id,
                )
            )
            uow.messages.update(
                user_message.id, ChatMessageUpdate(turn_status="failed")
            )
            uow.sessions.touch(session_id, user_id=user_id)
            uow.commit()
        return str(created.id)

    def mark_turn_failed(
        self,
        *,
        session_id: str,
        user_id: str,
        user_message_id: int,
    ) -> None:
        with self._uow_factory() as uow:
            self._require_owned_session(uow, session_id, user_id=user_id)
            user_message = self._require_user_message(
                uow, user_message_id, session_id=session_id, user_id=user_id
            )
            uow.messages.update(
                user_message.id, ChatMessageUpdate(turn_status="failed")
            )
            uow.commit()

    def _history_before(
        self,
        uow: ChatUnitOfWork,
        session_id: str,
        *,
        user_id: str,
    ) -> ConversationHistory:
        records = uow.messages.recent_for_session(
            session_id, user_id=user_id, limit=self._history_messages
        )
        history: ConversationHistory = []
        for record in records:
            if record.message_type in {"user_query", "agent_response"}:
                history.append(
                    {
                        "role": (
                            "assistant"
                            if record.message_type == "agent_response"
                            else "user"
                        ),
                        "content": record.content,
                    }
                )
        return history

    @staticmethod
    def _require_owned_session(
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
    def _require_user_message(
        uow: ChatUnitOfWork,
        message_id: int,
        *,
        session_id: str,
        user_id: str,
    ) -> ChatMessageRecord:
        message = uow.messages.get(message_id, user_id=user_id)
        if (
            message is None
            or message.session_id != session_id
            or message.message_type != "user_query"
        ):
            raise ChatTurnConflictError("user turn is missing")
        return message

    @staticmethod
    def _json_value(value: object) -> JsonValue:
        return to_json_value(value)


__all__ = ["ChatTurnPersistence", "ChatTurnStart"]
