"""管理用户范围内的会话与历史记录。"""

from __future__ import annotations

from typing import Optional

from safemeal.modules.conversation.contracts.chat.messages import (
    ChatSessionCreate,
    ChatSessionUpdate,
)
from safemeal.modules.conversation.ports.chat_repository import (
    ChatMessageRecord,
    ChatSessionRecord,
    ChatUnitOfWork,
    ChatUnitOfWorkFactory,
)
from safemeal.modules.conversation.application.chat_exceptions import (
    ChatSessionNotFoundError,
)


# 类说明（业务或基础设施实现类）：ChatSessionService
# 作用：实现聊天会话与历史消息管理服务，封装该组件的业务处理与依赖协作。
class ChatSessionService:
    # 方法说明：__init__
    # 作用：初始化聊天会话与历史消息管理服务，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   uow_factory（ChatUnitOfWorkFactory）：创建事务工作单元的工厂。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, uow_factory: ChatUnitOfWorkFactory) -> None:
        # 实例属性说明：_uow_factory
        # 作用：创建事务工作单元的工厂。
        self._uow_factory = uow_factory

    # 方法说明：list_sessions
    # 作用：按用户及活动状态分页读取会话。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   skip（int）：本次分页跳过的记录数量。
    #   limit（int）：本次查询或处理的最大条目数。
    #   active_only（bool）：是否仅查询活动记录。
    # 出参：list[ChatSessionRecord]；聊天会话仓储记录接口的集合。
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

    # 方法说明：create_session
    # 作用：创建用户会话并保留稳定的所有者标识。
    # 入参：
    #   data（ChatSessionCreate）：聊天会话创建命令。
    # 出参：ChatSessionRecord；聊天会话仓储记录接口。
    def create_session(self, data: ChatSessionCreate) -> ChatSessionRecord:
        with self._uow_factory() as uow:
            session = uow.sessions.create(data)
            uow.commit()
            return session

    # 方法说明：get_session
    # 作用：读取指定会话的持久化记录。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：Optional[ChatSessionRecord]；聊天会话仓储记录接口或 None。
    def get_session(
        self,
        session_id: str,
        *,
        user_id: str,
    ) -> Optional[ChatSessionRecord]:
        with self._uow_factory() as uow:
            return uow.sessions.get_active(session_id, user_id=user_id)

    # 方法说明：update_session
    # 作用：更新当前用户拥有会话的可修改字段。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   data（ChatSessionUpdate）：聊天会话更新命令。
    # 出参：Optional[ChatSessionRecord]；聊天会话仓储记录接口或 None。
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

    # 方法说明：delete_session
    # 作用：删除用户拥有的会话及其相关消息。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：Optional[ChatSessionRecord]；聊天会话仓储记录接口或 None。
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

    # 方法说明：count_sessions
    # 作用：统计满足用户和活动状态条件的会话总数。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：int；满足条件的会话总数。
    def count_sessions(self, user_id: str) -> int:
        with self._uow_factory() as uow:
            return uow.sessions.count_for_user(user_id)

    # 方法说明：list_messages
    # 作用：读取当前用户拥有会话的历史消息。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   offset（int）：本次分页跳过的记录数量。
    #   limit（int）：本次查询或处理的最大条目数。
    # 出参：list[ChatMessageRecord]；聊天消息仓储记录接口的集合。
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

    # 方法说明：get_message
    # 作用：按消息标识读取消息及其轮次状态。
    # 入参：
    #   message_id（int）：聊天消息标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：Optional[ChatMessageRecord]；聊天消息仓储记录接口或 None。
    def get_message(
        self,
        message_id: int,
        *,
        user_id: str,
    ) -> Optional[ChatMessageRecord]:
        with self._uow_factory() as uow:
            return uow.messages.get(message_id, user_id=user_id)

    # 方法说明：get_question_before_message
    # 作用：读取指定回复之前的用户问题。
    # 入参：
    #   message（ChatMessageRecord）：本轮用户消息或问题文本。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：Optional[str]；文本字符串或 None。
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

    # 方法说明：clear_messages
    # 作用：在保留会话的情况下清除该会话的消息。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：int；实际清除的消息数量。
    def clear_messages(self, session_id: str, *, user_id: str) -> int:
        with self._uow_factory() as uow:
            self._require_session(uow, session_id, user_id=user_id)
            uow.messages.next_order(session_id, user_id=user_id)
            deleted = uow.messages.delete_for_session(session_id)
            uow.commit()
            return deleted

    # 方法说明：_require_session
    # 作用：读取会话并拒绝不存在或不可使用的会话。
    # 入参：
    #   uow（ChatUnitOfWork）：当前事务工作单元。
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：ChatSessionRecord；聊天会话仓储记录接口。
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
