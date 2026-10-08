"""读取当前轮次之前的可信会话历史与活动菜单。"""

from safemeal.modules.conversation.ports.chat_repository import ChatUnitOfWorkFactory
from safemeal.modules.conversation.contracts.conversation.models import ConversationHistory
from safemeal.modules.conversation.application.chat_exceptions import ChatTurnConflictError
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
        history, _ = self.load_context_before_turn(
            user_id=user_id,
            session_id=session_id,
            source_message_id=source_message_id,
        )
        return history

    def load_context_before_turn(
        self, *, user_id: str, session_id: str, source_message_id: str
    ) -> tuple[ConversationHistory, JsonObject | None]:
        """在同一事务快照内读取历史消息和最近活动菜单。"""

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
            history = [
                {
                    "role": "assistant"
                    if row.message_type == "agent_response"
                    else "user",
                    "content": row.content,
                }
                for row in rows
                if row.message_type in {"user_query", "agent_response"}
            ]
            active_menu = None
            for row in reversed(rows):
                if row.message_type != "agent_response" or not row.message_metadata:
                    continue
                metadata = to_json_object(row.message_metadata)
                active = metadata.get("active_menu")
                if isinstance(active, dict):
                    active_menu = to_json_object(active)
                    break
                plan = metadata.get("menu_execution_plan")
                progress = metadata.get("menu_task_progress")
                if isinstance(plan, dict) and isinstance(progress, dict):
                    active_menu = {"plan": plan, "progress": progress}
                    break
            return history, active_menu

    def load_active_menu_before_turn(
        self, *, user_id: str, session_id: str, source_message_id: str
    ) -> JsonObject | None:

        _, active_menu = self.load_context_before_turn(
            user_id=user_id,
            session_id=session_id,
            source_message_id=source_message_id,
        )
        return active_menu
