"""定义应用层依赖的能力端口。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from types import TracebackType
from typing import List, Optional, Protocol, TypeAlias

from safemeal.modules.conversation.contracts.chat.messages import (
    ChatMessageCreate,
    ChatMessageUpdate,
    ChatSessionCreate,
    ChatSessionUpdate,
)
from safemeal.shared.types import JsonObject


# 类说明（接口类）：ChatSessionRecord
# 作用：定义聊天会话仓储记录接口的能力契约，供应用层与具体实现解耦。
class ChatSessionRecord(Protocol):
    # 字段说明：id
    # 作用：该业务记录的唯一标识，SQL 模型中通常对应主键。
    # 类型：str。
    id: str
    # 字段说明：title
    # 作用：会话、文档或菜谱标题。
    # 类型：str。
    title: str
    # 字段说明：user_id
    # 作用：经身份绑定后的持久化用户标识。
    # 类型：str。
    user_id: str
    # 字段说明：is_active
    # 作用：该记录或约束是否处于生效状态。
    # 类型：bool。
    is_active: bool
    # 字段说明：created_at
    # 作用：记录创建时间，用于排序和审计。
    # 类型：datetime。
    created_at: datetime
    # 字段说明：updated_at
    # 作用：记录最后更新时间。
    # 类型：Optional[datetime]。
    updated_at: Optional[datetime]


# 类说明（接口类）：ChatMessageRecord
# 作用：定义聊天消息仓储记录接口的能力契约，供应用层与具体实现解耦。
class ChatMessageRecord(Protocol):
    # 字段说明：id
    # 作用：该业务记录的唯一标识，SQL 模型中通常对应主键。
    # 类型：int。
    id: int
    # 字段说明：session_id
    # 作用：聊天会话或图检查点线程标识。
    # 类型：str。
    session_id: str
    # 字段说明：message_type
    # 作用：消息在对话流程中的业务类型。
    # 类型：str。
    message_type: str
    # 字段说明：content
    # 作用：当前文件、消息或证据的正文内容。
    # 类型：str。
    content: str
    # 字段说明：message_metadata
    # 作用：消息附属元数据，保存执行或来源信息。
    # 类型：Optional[JsonObject]。
    message_metadata: Optional[JsonObject]
    # 字段说明：order_index
    # 作用：对象在当前列表或会话内的顺序位置。
    # 类型：int。
    order_index: int
    # 字段说明：client_request_id
    # 作用：客户端提供的请求标识，用于识别同一请求并支持幂等处理。
    # 类型：Optional[str]。
    client_request_id: Optional[str]
    # 字段说明：reply_to_message_id
    # 作用：被当前回复关联的原始消息标识。
    # 类型：Optional[int]。
    reply_to_message_id: Optional[int]
    # 字段说明：turn_status
    # 作用：本轮对话或执行的最终状态。
    # 类型：Optional[str]。
    turn_status: Optional[str]
    # 字段说明：created_at
    # 作用：记录创建时间，用于排序和审计。
    # 类型：datetime。
    created_at: datetime
    # 字段说明：updated_at
    # 作用：记录最后更新时间。
    # 类型：Optional[datetime]。
    updated_at: Optional[datetime]


# 类说明（接口类）：ChatSessionRepository
# 作用：定义聊天会话仓储接口的能力契约，供应用层与具体实现解耦。
class ChatSessionRepository(Protocol):
    # 方法说明：get_active
    # 作用：按会话标识与用户归属读取活动会话。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：Optional[ChatSessionRecord]；聊天会话仓储记录接口或 None。
    def get_active(
        self,
        session_id: str,
        *,
        user_id: str,
    ) -> Optional[ChatSessionRecord]: ...

    # 方法说明：create
    # 作用：通过聊天会话仓储接口校验并创建新的业务对象。
    # 入参：
    #   data（ChatSessionCreate）：聊天会话创建命令。
    # 出参：ChatSessionRecord；聊天会话仓储记录接口。
    def create(self, data: ChatSessionCreate) -> ChatSessionRecord: ...

    # 方法说明：list_for_user
    # 作用：按用户和分页条件读取记录列表。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   skip（int）：本次分页跳过的记录数量。
    #   limit（int）：本次查询或处理的最大条目数。
    #   active_only（bool）：是否仅查询活动记录。
    # 出参：List[ChatSessionRecord]；聊天会话仓储记录接口的集合。
    def list_for_user(
        self,
        *,
        user_id: str,
        skip: int,
        limit: int,
        active_only: bool,
    ) -> List[ChatSessionRecord]: ...

    # 方法说明：update
    # 作用：通过聊天会话仓储接口更新指定业务对象的可修改字段。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   data（ChatSessionUpdate）：聊天会话更新命令。
    # 出参：Optional[ChatSessionRecord]；聊天会话仓储记录接口或 None。
    def update(
        self,
        session_id: str,
        *,
        user_id: str,
        data: ChatSessionUpdate,
    ) -> Optional[ChatSessionRecord]: ...

    # 方法说明：soft_delete
    # 作用：将业务记录标记为非活动状态，保留历史数据。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：Optional[ChatSessionRecord]；聊天会话仓储记录接口或 None。
    def soft_delete(
        self,
        session_id: str,
        *,
        user_id: str,
    ) -> Optional[ChatSessionRecord]: ...

    # 方法说明：touch
    # 作用：更新当前用户拥有的活动会话的最近修改时间。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：Optional[ChatSessionRecord]；聊天会话仓储记录接口或 None。
    def touch(
        self,
        session_id: str,
        *,
        user_id: str,
    ) -> Optional[ChatSessionRecord]: ...

    # 方法说明：count_for_user
    # 作用：统计当前用户可访问的记录总数。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：int；满足条件的会话总数。
    def count_for_user(self, user_id: str) -> int: ...


# 类说明（接口类）：ChatMessageRepository
# 作用：定义聊天消息仓储接口的能力契约，供应用层与具体实现解耦。
class ChatMessageRepository(Protocol):
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
    ) -> Optional[int]: ...

    # 方法说明：create
    # 作用：通过聊天消息仓储接口校验并创建新的业务对象。
    # 入参：
    #   data（ChatMessageCreate）：聊天消息创建命令。
    # 出参：ChatMessageRecord；聊天消息仓储记录接口。
    def create(self, data: ChatMessageCreate) -> ChatMessageRecord: ...

    # 方法说明：update
    # 作用：通过聊天消息仓储接口更新指定业务对象的可修改字段。
    # 入参：
    #   message_id（int）：聊天消息标识。
    #   data（ChatMessageUpdate）：聊天消息更新命令。
    # 出参：Optional[ChatMessageRecord]；聊天消息仓储记录接口或 None。
    def update(
        self,
        message_id: int,
        data: ChatMessageUpdate,
    ) -> Optional[ChatMessageRecord]: ...

    # 方法说明：get
    # 作用：通过聊天消息仓储接口读取指定标识对应的业务对象。
    # 入参：
    #   message_id（int）：聊天消息标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：Optional[ChatMessageRecord]；聊天消息仓储记录接口或 None。
    def get(
        self,
        message_id: int,
        *,
        user_id: str,
    ) -> Optional[ChatMessageRecord]: ...

    # 方法说明：list_for_session
    # 作用：按消息顺序读取指定会话的消息。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   offset（int）：本次分页跳过的记录数量。
    #   limit（int）：本次查询或处理的最大条目数。
    # 出参：List[ChatMessageRecord]；聊天消息仓储记录接口的集合。
    def list_for_session(
        self,
        session_id: str,
        *,
        user_id: str,
        offset: int,
        limit: int,
    ) -> List[ChatMessageRecord]: ...

    # 方法说明：recent_for_session
    # 作用：读取指定会话最近的历史消息。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   limit（int）：本次查询或处理的最大条目数。
    #   before_order_index（Optional[int]）：仅读取此消息顺序号之前的历史；默认值为 None。
    # 出参：List[ChatMessageRecord]；聊天消息仓储记录接口的集合。
    def recent_for_session(
        self,
        session_id: str,
        *,
        user_id: str,
        limit: int,
        before_order_index: Optional[int] = None,
    ) -> List[ChatMessageRecord]: ...

    # 方法说明：previous_user_message
    # 作用：从历史中寻找当前问题之前的用户消息。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   before_order_index（int）：仅读取此消息顺序号之前的历史。
    # 出参：Optional[ChatMessageRecord]；聊天消息仓储记录接口或 None。
    def previous_user_message(
        self,
        session_id: str,
        *,
        user_id: str,
        before_order_index: int,
    ) -> Optional[ChatMessageRecord]: ...

    # 方法说明：claim_approval
    # 作用：按消息、审批标识和待处理状态原子认领审批执行权。
    # 入参：
    #   message_id（int）：聊天消息标识。
    #   approval_id（str）：绑定当前待审批操作的审批标识。
    #   metadata（JsonObject）：文档、消息或证据的来源与辅助元数据。
    # 出参：bool；布尔判定值。
    def claim_approval(
        self, message_id: int, *, approval_id: str, metadata: JsonObject
    ) -> bool: ...

    # 方法说明：delete_for_session
    # 作用：删除指定会话下的全部消息。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    # 出参：int；实际清除的消息数量。
    def delete_for_session(self, session_id: str) -> int: ...


# 类说明（接口类）：ChatUnitOfWork
# 作用：定义聊天业务事务工作单元接口的能力契约，供应用层与具体实现解耦。
class ChatUnitOfWork(Protocol):
    # 方法说明：sessions
    # 作用：取得当前工作单元的会话仓储。
    # 入参：
    #   无显式入参。
    # 出参：ChatSessionRepository；聊天会话仓储接口。
    @property
    def sessions(self) -> ChatSessionRepository: ...

    # 方法说明：messages
    # 作用：取得当前工作单元绑定的聊天消息仓储。
    # 入参：
    #   无显式入参。
    # 出参：ChatMessageRepository；当前事务内的聊天消息仓储。
    @property
    def messages(self) -> ChatMessageRepository: ...

    # 方法说明：commit
    # 作用：提交当前工作单元的数据库事务。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def commit(self) -> None: ...

    # 方法说明：rollback
    # 作用：回滚当前工作单元的数据库事务。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def rollback(self) -> None: ...

    # 方法说明：__enter__
    # 作用：进入工作单元并创建事务资源，供 with 块内的仓储操作共享。
    # 入参：
    #   无显式入参。
    # 出参：'ChatUnitOfWork'；聊天业务事务工作单元接口。
    def __enter__(self) -> "ChatUnitOfWork": ...

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
