"""读取当前轮次之前的可信会话历史与活动菜单。"""

from safemeal.application.ports.persistence.chat_repository import ChatUnitOfWorkFactory
from safemeal.application.contracts.conversation.models import ConversationHistory
from safemeal.application.service.chat.chat_exceptions import ChatTurnConflictError
from safemeal.shared.types import JsonObject, to_json_object


class ConversationHistoryService:
    def __init__(
        self, uow_factory: ChatUnitOfWorkFactory, *, history_messages: int = 12
    ):
        if history_messages < 0:
            raise ValueError("history_messages must be non-negative")
        self._uow_factory = uow_factory
        self._history_messages = history_messages

    def load_before_turn(
        self, *, user_id: str, session_id: str, source_message_id: str
    ) -> ConversationHistory:
        with self._uow_factory() as uow:
            current = uow.messages.get(int(source_message_id), user_id=user_id)
            if (
                current is None
                or current.session_id != session_id
                or current.message_type != "user_query"
                or uow.sessions.get_active(session_id, user_id=user_id) is None
            ):
                raise ChatTurnConflictError("user turn is missing")
            rows = uow.messages.recent_for_session(
                session_id,
                user_id=user_id,
                limit=self._history_messages,
                before_order_index=current.order_index,
            )
            return [
                {
                    "role": "assistant"
                    if row.message_type == "agent_response"
                    else "user",
                    "content": row.content,
                }
                for row in rows
                if row.message_type in {"user_query", "agent_response"}
            ]

    def load_active_menu_before_turn(
        self, *, user_id: str, session_id: str, source_message_id: str
    ) -> JsonObject | None:

        with self._uow_factory() as uow:
            current = uow.messages.get(int(source_message_id), user_id=user_id)
            if current is None or current.session_id != session_id:
                raise ChatTurnConflictError("user turn is missing")
            rows = uow.messages.recent_for_session(
                session_id,
                user_id=user_id,
                limit=self._history_messages,
                before_order_index=current.order_index,
            )
            for row in reversed(rows):
                if row.message_type != "agent_response" or not row.message_metadata:
                    continue
                metadata = to_json_object(row.message_metadata)
                active = metadata.get("active_menu")
                if isinstance(active, dict):
                    return to_json_object(active)
                plan = metadata.get("menu_execution_plan")
                progress = metadata.get("menu_task_progress")
                if isinstance(plan, dict) and isinstance(progress, dict):
                    return {"plan": plan, "progress": progress}
            return None
