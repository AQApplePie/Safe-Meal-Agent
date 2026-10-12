"""实现持久化基础设施适配。"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from types import TracebackType
from typing import List, Optional, cast

from sqlalchemy import desc, func, select, update, or_, and_
from safemeal.modules.conversation.application.chat_exceptions import (
    ChatTurnConflictError,
)
from sqlalchemy.orm import Query, Session

from safemeal.modules.conversation.contracts.chat.messages import (
    ChatMessageCreate,
    ChatMessageUpdate,
    ChatSessionCreate,
    ChatSessionUpdate,
)
from safemeal.modules.conversation.ports.chat_repository import ChatUnitOfWork
from safemeal.infrastructure.persistence.database import session_scope
from safemeal.infrastructure.persistence.db.models import (
    ChatMessage,
    ChatSession,
)


# 类说明（SQL 类）：SqlAlchemyChatSessionRepository
# 作用：实现聊天会话 SQL 仓储的查询、写入或运行状态持久化。
class SqlAlchemyChatSessionRepository:
    # 方法说明：__init__
    # 作用：初始化聊天会话 SQL 仓储，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   session（Session）：当前 SQL 会话或聊天会话对象。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, session: Session) -> None:
        # 实例属性说明：_session
        # 作用：当前 SQL 会话或聊天会话对象。
        self._session = session

    # 方法说明：get_active
    # 作用：按会话标识与用户归属读取活动会话。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：Optional[ChatSession]；聊天会话数据库模型或 None。
    def get_active(self, session_id: str, *, user_id: str) -> Optional[ChatSession]:
        return self._active_query(session_id, user_id=user_id).one_or_none()

    # 方法说明：create
    # 作用：通过聊天会话 SQL 仓储校验并创建新的业务对象。
    # 入参：
    #   data（ChatSessionCreate）：聊天会话创建命令。
    # 出参：ChatSession；聊天会话数据库模型。
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

    # 方法说明：list_for_user
    # 作用：按用户和分页条件读取记录列表。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   skip（int）：本次分页跳过的记录数量。
    #   limit（int）：本次查询或处理的最大条目数。
    #   active_only（bool）：是否仅查询活动记录。
    # 出参：List[ChatSession]；聊天会话数据库模型的集合。
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

    # 方法说明：update
    # 作用：通过聊天会话 SQL 仓储更新指定业务对象的可修改字段。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   data（ChatSessionUpdate）：聊天会话更新命令。
    # 出参：Optional[ChatSession]；聊天会话数据库模型或 None。
    def update(
        self,
        session_id: str,
        *,
        user_id: str,
        data: ChatSessionUpdate,
    ) -> Optional[ChatSession]:
        entity = self.get_active(session_id, user_id=user_id)
        if entity is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(entity, field, value)
        setattr(entity, "updated_at", datetime.now(timezone.utc))
        self._session.flush()
        return entity

    # 方法说明：soft_delete
    # 作用：将业务记录标记为非活动状态，保留历史数据。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：Optional[ChatSession]；聊天会话数据库模型或 None。
    def soft_delete(
        self,
        session_id: str,
        *,
        user_id: str,
    ) -> Optional[ChatSession]:
        entity = self.get_active(session_id, user_id=user_id)
        if entity is not None:
            setattr(entity, "is_active", False)
            setattr(entity, "updated_at", datetime.now(timezone.utc))
            self._session.flush()
        return entity

    # 方法说明：touch
    # 作用：更新当前用户拥有的活动会话的最近修改时间。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：Optional[ChatSession]；聊天会话数据库模型或 None。
    def touch(self, session_id: str, *, user_id: str) -> Optional[ChatSession]:
        entity = self.get_active(session_id, user_id=user_id)
        if entity is not None:
            setattr(entity, "updated_at", datetime.now(timezone.utc))
            self._session.flush()
        return entity

    # 方法说明：count_for_user
    # 作用：统计当前用户可访问的记录总数。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：int；满足条件的会话总数。
    def count_for_user(self, user_id: str) -> int:
        return (
            self._session.query(ChatSession)
            .filter(ChatSession.user_id == user_id)
            .count()
        )

    # 方法说明：_active_query
    # 作用：构造同时限制会话标识、用户归属和活动状态的 SQL 查询。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：Query[ChatSession]；按 Query[ChatSession] 签名约定的结果。
    def _active_query(self, session_id: str, *, user_id: str) -> Query[ChatSession]:
        return self._session.query(ChatSession).filter(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
            ChatSession.is_active.is_(True),
        )


# 类说明（SQL 类）：SqlAlchemyChatMessageRepository
# 作用：实现聊天消息 SQL 仓储的查询、写入或运行状态持久化。
class SqlAlchemyChatMessageRepository:
    # 方法说明：__init__
    # 作用：初始化聊天消息 SQL 仓储，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   session（Session）：当前 SQL 会话或聊天会话对象。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, session: Session) -> None:
        # 实例属性说明：_session
        # 作用：当前 SQL 会话或聊天会话对象。
        self._session = session

    # 方法说明：next_order
    # 作用：原子预留会话内下一条消息的顺序号。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：Optional[int]；整数或 None。
    def next_order(
        self,
        session_id: str,
        *,
        user_id: str,
    ) -> Optional[int]:
        active = self._session.execute(
            select(ChatSession.id).where(
                ChatSession.id == session_id,
                ChatSession.user_id == user_id,
                ChatSession.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if active is None:
            return None
        open_turn = self._session.execute(
            select(ChatMessage.id)
            .where(
                ChatMessage.session_id == session_id,
                or_(
                    and_(
                        ChatMessage.message_type == "user_query",
                        ChatMessage.turn_status == "processing",
                    ),
                    and_(
                        ChatMessage.message_type == "agent_response",
                        or_(
                            ChatMessage.message_metadata["approval_required"]
                            .as_boolean()
                            .is_(True),
                            ChatMessage.turn_status.in_(("processing", "failed")),
                        ),
                    ),
                ),
            )
            .limit(1)
        ).scalar_one_or_none()
        if open_turn is not None:
            raise ChatTurnConflictError(
                "Resolve the pending approval or processing turn before starting another turn"
            )
        latest = self._session.execute(
            select(func.max(ChatMessage.order_index)).where(
                ChatMessage.session_id == session_id
            )
        ).scalar_one()
        return int(latest or 0) + 1

    # 方法说明：create
    # 作用：通过聊天消息 SQL 仓储校验并创建新的业务对象。
    # 入参：
    #   data（ChatMessageCreate）：聊天消息创建命令。
    # 出参：ChatMessage；聊天消息数据库模型。
    def create(self, data: ChatMessageCreate) -> ChatMessage:
        entity = ChatMessage(**data.model_dump())
        self._session.add(entity)
        self._session.flush()
        return entity

    # 方法说明：update
    # 作用：通过聊天消息 SQL 仓储更新指定业务对象的可修改字段。
    # 入参：
    #   message_id（int）：聊天消息标识。
    #   data（ChatMessageUpdate）：聊天消息更新命令。
    # 出参：Optional[ChatMessage]；聊天消息数据库模型或 None。
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

    # 方法说明：get
    # 作用：通过聊天消息 SQL 仓储读取指定标识对应的业务对象。
    # 入参：
    #   message_id（int）：聊天消息标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：Optional[ChatMessage]；聊天消息数据库模型或 None。
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

    # 方法说明：list_for_session
    # 作用：按消息顺序读取指定会话的消息。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   offset（int）：本次分页跳过的记录数量。
    #   limit（int）：本次查询或处理的最大条目数。
    # 出参：List[ChatMessage]；聊天消息数据库模型的集合。
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

    # 方法说明：recent_for_session
    # 作用：读取指定会话最近的历史消息。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   limit（int）：本次查询或处理的最大条目数。
    #   before_order_index（Optional[int]）：仅读取此消息顺序号之前的历史；默认值为 None。
    # 出参：List[ChatMessage]；聊天消息数据库模型的集合。
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

    # 方法说明：previous_user_message
    # 作用：从历史中寻找当前问题之前的用户消息。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   before_order_index（int）：仅读取此消息顺序号之前的历史。
    # 出参：Optional[ChatMessage]；聊天消息数据库模型或 None。
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

    # 方法说明：claim_approval
    # 作用：按消息、审批标识和待处理状态原子认领审批执行权。
    # 入参：
    #   message_id（int）：聊天消息标识。
    #   approval_id（str）：绑定当前待审批操作的审批标识。
    #   metadata（dict）：文档、消息或证据的来源与辅助元数据。
    # 出参：bool；布尔判定值。
    def claim_approval(
        self, message_id: int, *, approval_id: str, metadata: dict
    ) -> bool:
        result = self._session.execute(
            update(ChatMessage)
            .where(
                ChatMessage.id == message_id,
                ChatMessage.message_type == "agent_response",
                ChatMessage.turn_status.is_(None),
                ChatMessage.message_metadata["approval_required"]
                .as_boolean()
                .is_(True),
                ChatMessage.message_metadata["approval_id"].as_string() == approval_id,
            )
            .values(
                turn_status="processing",
                message_metadata=metadata,
                updated_at=datetime.now(timezone.utc),
            )
        )
        return result.rowcount == 1

    # 方法说明：delete_for_session
    # 作用：删除指定会话下的全部消息。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    # 出参：int；实际清除的消息数量。
    def delete_for_session(self, session_id: str) -> int:
        return int(
            self._session.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .delete(synchronize_session=False)
            or 0
        )


# 类说明（SQL 类）：SqlAlchemyChatUnitOfWork
# 作用：管理聊天 SQL 事务工作单元的会话、提交与回滚边界。
class SqlAlchemyChatUnitOfWork:
    # 方法说明：__init__
    # 作用：初始化聊天 SQL 事务工作单元，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   session_factory（Callable[[], Session] | None）：创建 SQLAlchemy 会话的工厂；默认值为
    # None。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        # 实例属性说明：_session_factory
        # 作用：创建 SQLAlchemy 会话的工厂。
        self._session_factory = session_factory
        # 实例属性说明：_scope
        # 作用：当前请求或查询的可信范围。
        # 类型：AbstractContextManager[Session] | None。
        # 初始值：None。
        self._scope: AbstractContextManager[Session] | None = None
        # 实例属性说明：_session
        # 作用：当前 SQL 会话或聊天会话对象。
        # 类型：Session | None。
        # 初始值：None。
        self._session: Session | None = None
        # 实例属性说明：_sessions
        # 作用：SQLAlchemy 会话工厂。
        # 类型：SqlAlchemyChatSessionRepository | None。
        # 初始值：None。
        self._sessions: SqlAlchemyChatSessionRepository | None = None
        # 实例属性说明：_messages
        # 作用：按顺序组织的历史对话消息。
        # 类型：SqlAlchemyChatMessageRepository | None。
        # 初始值：None。
        self._messages: SqlAlchemyChatMessageRepository | None = None

    # 方法说明：sessions
    # 作用：取得当前工作单元的会话仓储。
    # 入参：
    #   无显式入参。
    # 出参：SqlAlchemyChatSessionRepository；聊天会话 SQL 仓储。
    @property
    def sessions(self) -> SqlAlchemyChatSessionRepository:
        if self._sessions is None:
            raise RuntimeError("chat Unit of Work is not active")
        return self._sessions

    # 方法说明：messages
    # 作用：取得当前工作单元绑定的聊天消息仓储。
    # 入参：
    #   无显式入参。
    # 出参：SqlAlchemyChatMessageRepository；当前事务内的聊天消息仓储。
    @property
    def messages(self) -> SqlAlchemyChatMessageRepository:
        if self._messages is None:
            raise RuntimeError("chat Unit of Work is not active")
        return self._messages

    # 方法说明：__enter__
    # 作用：进入工作单元并创建事务资源，供 with 块内的仓储操作共享。
    # 入参：
    #   无显式入参。
    # 出参：'SqlAlchemyChatUnitOfWork'；聊天 SQL 事务工作单元。
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

    # 方法说明：commit
    # 作用：提交当前工作单元的数据库事务。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def commit(self) -> None:
        self._require_session().commit()

    # 方法说明：rollback
    # 作用：回滚当前工作单元的数据库事务。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def rollback(self) -> None:
        self._require_session().rollback()

    # 方法说明：__exit__
    # 作用：退出工作单元；异常时回滚事务，并关闭会话释放连接。
    # 入参：
    #   exc_type（type[BaseException] | None）：退出上下文时的异常类型。
    #   exc_value（BaseException | None）：当前捕获或退出上下文时传入的异常对象。
    #   traceback（TracebackType | None）：退出上下文时传入的异常堆栈。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
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

    # 方法说明：_require_session
    # 作用：取得当前工作单元已打开的 SQLAlchemy 会话；事务未启用时抛错。
    # 入参：
    #   无显式入参。
    # 出参：Session；SQLAlchemy 会话。
    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("chat Unit of Work is not active")
        return self._session


# 方法说明：sqlalchemy_chat_unit_of_work
# 作用：创建会话模块 SQL 事务工作单元上下文。
# 入参：
#   无显式入参。
# 出参：ChatUnitOfWork；事务工作单元上下文；进入 with 块时取得对应事务和仓储能力。
def sqlalchemy_chat_unit_of_work() -> ChatUnitOfWork:

    return cast(ChatUnitOfWork, SqlAlchemyChatUnitOfWork())


__all__ = [
    "SqlAlchemyChatMessageRepository",
    "SqlAlchemyChatSessionRepository",
    "SqlAlchemyChatUnitOfWork",
    "sqlalchemy_chat_unit_of_work",
]
