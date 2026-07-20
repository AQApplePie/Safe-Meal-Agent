"""Persistence orchestration for a durable, idempotent chat turn."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional
from uuid import NAMESPACE_URL, uuid4, uuid5

from SafeMealAgent.back.application.contracts.chat import (
    ChatMessageCreate,
    ChatMessageUpdate,
    ChatSessionCreate,
)
from SafeMealAgent.back.application.ports.chat_repository import (
    ChatMessageRecord,
    ChatSessionRecord,
    ChatUnitOfWork,
    ChatUnitOfWorkFactory,
)
from SafeMealAgent.back.application.use_cases.chat.errors import (
    ChatRequestConflictError,
    ChatSessionNotFoundError,
    ChatTurnConflictError,
    ChatTurnInProgressError,
)
from SafeMealAgent.back.shared.contracts.common import ConversationHistory
from SafeMealAgent.back.shared.types import JsonObject, JsonValue, to_json_object, to_json_value


_RESPONSE_ENVELOPE_KEY = "_chat_response"
_GENERIC_AGENT_ERROR = "抱歉，处理您的请求时出现了错误。请稍后重试。"


@dataclass(frozen=True)
class ChatTurnStart:
    """Durable state allocated before an Agent invocation begins."""

    session_id: str
    user_message_id: int
    response_order_index: int
    history: ConversationHistory
    replayed_response: Optional[ChatMessageRecord] = None


class ChatPersistenceService:
    """Coordinate conversation persistence through a database-independent port."""

    def __init__(
        self,
        uow_factory: ChatUnitOfWorkFactory,
        *,
        history_messages: int = 12,
        processing_timeout_seconds: int = 600,
    ) -> None:
        if history_messages < 0:
            raise ValueError("history_messages must be non-negative")
        if processing_timeout_seconds <= 0:
            raise ValueError("processing_timeout_seconds must be positive")
        self._uow_factory = uow_factory
        self._history_messages = history_messages
        self._processing_timeout = timedelta(seconds=processing_timeout_seconds)

    def start_turn(
        self,
        session_id: Optional[str],
        user_id: str,
        message: str,
        *,
        request_id: Optional[str] = None,
    ) -> ChatTurnStart:
        """Create or resume a turn while atomically reserving question/answer positions.

        Reusing a supplied session ID never creates a replacement session: a missing
        or foreign-owned ID is reported identically as not found. A request ID is
        scoped to the session and lets completed requests replay the persisted answer.
        """

        with self._uow_factory() as uow:
            if session_id is None:
                # A deterministic ID makes a timed-out first request retryable even
                # when the client never received the newly generated session ID.
                session_id = (
                    str(uuid5(NAMESPACE_URL, f"safemeal:{user_id}:{request_id}"))
                    if request_id
                    else str(uuid4())
                )
                session = uow.sessions.get_active_for_update(
                    session_id,
                    user_id=user_id,
                )
                if session is None:
                    uow.sessions.create(
                        ChatSessionCreate(
                            id=session_id,
                            user_id=user_id,
                            title=f"Chat {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
                        )
                    )
            else:
                session = uow.sessions.get_active_for_update(
                    session_id,
                    user_id=user_id,
                )
                if session is None:
                    raise ChatSessionNotFoundError()

            if request_id:
                existing = uow.messages.get_by_request_id(
                    session_id,
                    user_id=user_id,
                    request_id=request_id,
                )
                if existing is not None:
                    resumed, changed = self._resume_turn(
                        uow,
                        existing,
                        user_id=user_id,
                        message=message,
                    )
                    if changed:
                        uow.commit()
                    return resumed

            first_order = uow.messages.reserve_orders(
                session_id,
                user_id=user_id,
                count=2,
            )
            if first_order is None:
                raise ChatSessionNotFoundError()
            # Read history after the allocator update has obtained the session's
            # write lock. This avoids read-to-write upgrade deadlocks on SQLite
            # while the reserved positions remain invisible to history queries.
            history = self._history_before(
                uow,
                session_id,
                user_id=user_id,
            )

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
        """Persist a successful answer and return its real database ID."""

        response_metadata = dict(metadata or {})
        if route:
            response_metadata["route"] = route
        response_metadata[_RESPONSE_ENVELOPE_KEY] = {
            "route": route,
            "route_logic": route_logic,
            "sources": [self._json_value(source) for source in sources],
            "metadata": dict(metadata or {}),
        }

        with self._uow_factory() as uow:
            self._require_owned_session(
                uow,
                session_id,
                user_id=user_id,
            )
            user_message = self._require_user_message(
                uow,
                user_message_id,
                session_id=session_id,
                user_id=user_id,
            )
            existing = uow.messages.get_response_for(
                user_message_id,
                user_id=user_id,
            )
            if existing is None:
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
            elif existing.message_type == "error":
                updated = uow.messages.update(
                    existing.id,
                    ChatMessageUpdate(
                        message_type="agent_response",
                        content=response,
                        message_metadata=response_metadata,
                    ),
                )
                if updated is None:  # pragma: no cover - protected by row lock
                    raise ChatTurnConflictError("reserved response disappeared")
                created = updated
            else:
                created = existing

            uow.messages.update(
                user_message.id,
                ChatMessageUpdate(turn_status="completed"),
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
        """Persist a generic failure marker without leaking provider exceptions."""

        with self._uow_factory() as uow:
            self._require_owned_session(
                uow,
                session_id,
                user_id=user_id,
            )
            user_message = self._require_user_message(
                uow,
                user_message_id,
                session_id=session_id,
                user_id=user_id,
            )
            existing = uow.messages.get_response_for(
                user_message_id,
                user_id=user_id,
            )
            if existing is None:
                error_message = uow.messages.create(
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
            else:
                error_message = existing
            uow.messages.update(
                user_message.id,
                ChatMessageUpdate(turn_status="failed"),
            )
            uow.sessions.touch(session_id, user_id=user_id)
            uow.commit()
        return str(error_message.id)

    def mark_turn_failed(
        self,
        *,
        session_id: str,
        user_id: str,
        user_message_id: int,
    ) -> None:
        """Release an idempotency key for retry after a non-Agent failure."""

        with self._uow_factory() as uow:
            self._require_owned_session(
                uow,
                session_id,
                user_id=user_id,
            )
            user_message = self._require_user_message(
                uow,
                user_message_id,
                session_id=session_id,
                user_id=user_id,
            )
            uow.messages.update(
                user_message.id,
                ChatMessageUpdate(turn_status="failed"),
            )
            uow.commit()

    def _resume_turn(
        self,
        uow: ChatUnitOfWork,
        existing: ChatMessageRecord,
        *,
        user_id: str,
        message: str,
    ) -> tuple[ChatTurnStart, bool]:
        if existing.content != message:
            raise ChatRequestConflictError()

        response = uow.messages.get_response_for(existing.id, user_id=user_id)
        if existing.turn_status == "completed":
            if response is None or response.message_type != "agent_response":
                raise ChatTurnConflictError(
                    "completed chat turn has no persisted response"
                )
            return (
                ChatTurnStart(
                    session_id=existing.session_id,
                    user_message_id=existing.id,
                    response_order_index=existing.order_index + 1,
                    history=[],
                    replayed_response=response,
                ),
                False,
            )

        if existing.turn_status == "processing" and not self._processing_is_stale(
            existing
        ):
            raise ChatTurnInProgressError()

        uow.messages.update(
            existing.id,
            ChatMessageUpdate(turn_status="processing"),
        )
        history = self._history_before(
            uow,
            existing.session_id,
            user_id=user_id,
            before_order_index=existing.order_index,
        )
        return (
            ChatTurnStart(
                session_id=existing.session_id,
                user_message_id=existing.id,
                response_order_index=existing.order_index + 1,
                history=history,
            ),
            True,
        )

    def _processing_is_stale(self, message: ChatMessageRecord) -> bool:
        updated_at = message.updated_at or message.created_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - updated_at >= self._processing_timeout

    def _history_before(
        self,
        uow: ChatUnitOfWork,
        session_id: str,
        *,
        user_id: str,
        before_order_index: Optional[int] = None,
    ) -> ConversationHistory:
        return self._history_from_records(
            uow.messages.recent_for_session(
                session_id,
                user_id=user_id,
                limit=self._history_messages,
                before_order_index=before_order_index,
            )
        )

    def _require_owned_session(
        self,
        uow: ChatUnitOfWork,
        session_id: str,
        *,
        user_id: str,
    ) -> ChatSessionRecord:
        session = uow.sessions.get_active_for_update(session_id, user_id=user_id)
        if session is None:
            raise ChatSessionNotFoundError()
        return session

    def _require_user_message(
        self,
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
    def _history_from_records(records: list[ChatMessageRecord]) -> ConversationHistory:
        history: ConversationHistory = []
        for record in records:
            if record.message_type not in {"user_query", "agent_response"}:
                continue
            role = "assistant" if record.message_type == "agent_response" else "user"
            if record.content and record.content.strip():
                history.append({"role": role, "content": record.content})
        return history

    @staticmethod
    def _json_value(value: object) -> JsonValue:
        return to_json_value(value)


def response_envelope(record: ChatMessageRecord) -> JsonObject:
    """Return the replay metadata stored with an Agent response."""

    metadata = record.message_metadata or {}
    value = metadata.get(_RESPONSE_ENVELOPE_KEY)
    return to_json_object(value) if isinstance(value, dict) else {}


__all__ = ["ChatPersistenceService", "ChatTurnStart", "response_envelope"]
