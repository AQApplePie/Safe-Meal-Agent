"""读取当前轮次之前的可信会话历史与活动菜单。"""

from safemeal.modules.conversation.ports.chat_repository import ChatUnitOfWorkFactory
from safemeal.modules.conversation.contracts.conversation.models import (
    ConversationHistory,
)
from safemeal.modules.conversation.application.chat_exceptions import (
    ChatTurnConflictError,
)
from safemeal.shared.types import JsonObject, to_json_object


# 类说明（业务或基础设施实现类）：ConversationHistoryService
# 作用：实现历史消息与活动菜单读取服务，封装该组件的业务处理与依赖协作。
class ConversationHistoryService:
    # 方法说明：__init__
    # 作用：初始化历史消息与活动菜单读取服务，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   uow_factory（ChatUnitOfWorkFactory）：创建事务工作单元的工厂。
    #   history_messages（int）：按顺序组织的历史对话消息；默认值为 12。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(
        self, uow_factory: ChatUnitOfWorkFactory, *, history_messages: int = 12
    ):
        if history_messages < 0:
            raise ValueError("history_messages must be non-negative")
        # 实例属性说明：_uow_factory
        # 作用：创建事务工作单元的工厂。
        self._uow_factory = uow_factory
        # 实例属性说明：_history_messages
        # 作用：按顺序组织的历史对话消息。
        self._history_messages = history_messages

    # 方法说明：load_context_before_turn
    # 作用：在同一事务快照内读取历史消息和最近活动菜单。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   source_message_id（str）：记忆或结果对应的来源消息标识。
    # 出参：tuple[ConversationHistory, JsonObject | None]；历史对话上下文、JSON
    # 字段映射或None（未取得结果）组成的元组。
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
