"""用户长期记忆仓储端口。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from types import TracebackType
from typing import List, Optional, Protocol, TypeAlias

from safemeal.modules.conversation.contracts.memory.models import (
    UserMemoryCreate,
    UserMemoryUpdate,
)
from safemeal.shared.types import JsonObject


# 类说明（接口类）：UserMemoryRecord
# 作用：仓储返回的用户记忆记录结构。
class UserMemoryRecord(Protocol):
    """仓储返回的用户记忆记录结构。

    该协议只描述应用层实际需要读取的字段，不绑定 SQLAlchemy ORM 类。
    """

    # 字段说明：id
    # 作用：该业务记录的唯一标识，SQL 模型中通常对应主键。
    # 类型：int。
    id: int
    # 字段说明：user_id
    # 作用：经身份绑定后的持久化用户标识。
    # 类型：str。
    user_id: str
    # 字段说明：memory_type
    # 作用：长期记忆类型。
    # 类型：str。
    memory_type: str
    # 字段说明：memory_key
    # 作用：机器可读的长期记忆事实键。
    # 类型：str。
    memory_key: str
    # 字段说明：memory_value
    # 作用：长期记忆的人类可读内容。
    # 类型：str。
    memory_value: str
    # 字段说明：confidence
    # 作用：该记忆事实的置信度，范围为 0 至 1；显式安全约束仍按可信规则处理。
    # 类型：float。
    confidence: float
    # 字段说明：source
    # 作用：数据来源标识或提供该数据的对象。
    # 类型：str。
    source: str
    # 字段说明：status
    # 作用：HTTP 状态码或业务状态。
    # 类型：str。
    status: str
    # 字段说明：source_session_id
    # 作用：记忆或结果对应的来源会话标识。
    # 类型：Optional[str]。
    source_session_id: Optional[str]
    # 字段说明：source_message_id
    # 作用：记忆或结果对应的来源消息标识。
    # 类型：Optional[str]。
    source_message_id: Optional[str]
    # 字段说明：memory_metadata
    # 作用：记忆的来源及辅助元数据。
    # 类型：Optional[JsonObject]。
    memory_metadata: Optional[JsonObject]
    # 字段说明：created_at
    # 作用：记录创建时间，用于排序和审计。
    # 类型：datetime。
    created_at: datetime
    # 字段说明：updated_at
    # 作用：记录最后更新时间。
    # 类型：Optional[datetime]。
    updated_at: Optional[datetime]
    # 字段说明：last_used_at
    # 作用：凭据或资源最近一次使用时间。
    # 类型：Optional[datetime]。
    last_used_at: Optional[datetime]


# 类说明（接口类）：UserMemoryRepository
# 作用：应用层依赖的用户记忆仓储接口，由基础设施层实现。
class UserMemoryRepository(Protocol):
    """应用层依赖的用户记忆仓储接口，由基础设施层实现。"""

    # 方法说明：upsert_memory
    # 作用：按用户、类型与事实键幂等保存记忆，更新置信度及来源。
    # 入参：
    #   data（UserMemoryCreate）：用户长期记忆创建命令。
    # 出参：UserMemoryRecord；长期记忆仓储记录接口。
    def upsert_memory(self, data: UserMemoryCreate) -> UserMemoryRecord: ...

    # 方法说明：get_memory
    # 作用：读取指定用户记忆并校验归属。
    # 入参：
    #   memory_id（int）：长期记忆标识。
    # 出参：Optional[UserMemoryRecord]；长期记忆仓储记录接口或 None。
    def get_memory(self, memory_id: int) -> Optional[UserMemoryRecord]: ...

    # 方法说明：list_active_memories
    # 作用：列出当前用户的活动长期记忆。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   memory_type（Optional[str]）：长期记忆类型；默认值为 None。
    #   limit（int | None）：本次查询或处理的最大条目数；默认值为 50。
    # 出参：List[UserMemoryRecord]；长期记忆仓储记录接口的集合。
    def list_active_memories(
        self,
        user_id: str,
        *,
        memory_type: Optional[str] = None,
        limit: int | None = 50,
    ) -> List[UserMemoryRecord]: ...

    # 方法说明：list_memories
    # 作用：读取用户长期记忆并按状态、类型等条件过滤。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   include_archived（bool）：是否包含归档记忆；默认值为 False。
    #   limit（int）：本次查询或处理的最大条目数；默认值为 100。
    # 出参：List[UserMemoryRecord]；长期记忆仓储记录接口的集合。
    def list_memories(
        self,
        user_id: str,
        *,
        include_archived: bool = False,
        limit: int = 100,
    ) -> List[UserMemoryRecord]: ...

    # 方法说明：update_memory
    # 作用：更新归属当前用户的长期记忆字段。
    # 入参：
    #   memory_id（int）：长期记忆标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   data（UserMemoryUpdate）：长期记忆更新命令。
    # 出参：Optional[UserMemoryRecord]；长期记忆仓储记录接口或 None。
    def update_memory(
        self,
        memory_id: int,
        user_id: str,
        data: UserMemoryUpdate,
    ) -> Optional[UserMemoryRecord]: ...

    # 方法说明：archive_memory
    # 作用：将指定长期记忆归档，保留历史记录而停止参与当前上下文。
    # 入参：
    #   memory_id（int）：长期记忆标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：Optional[UserMemoryRecord]；长期记忆仓储记录接口或 None。
    def archive_memory(
        self,
        memory_id: int,
        user_id: str,
    ) -> Optional[UserMemoryRecord]: ...

    # 方法说明：mark_used
    # 作用：更新记忆最近使用时间或使用统计。
    # 入参：
    #   memory_ids（List[int]）：待更新长期记忆标识集合。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def mark_used(self, memory_ids: List[int]) -> None: ...

    # 方法说明：archive_active_dietary_memories
    # 作用：归档已撤回的活动饮食记忆，避免继续参与安全约束。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   memory_keys（List[str]）：记忆事实键集合。
    # 出参：int；实际归档的活动饮食记忆数量。
    def archive_active_dietary_memories(
        self,
        user_id: str,
        memory_keys: List[str],
    ) -> int: ...


# 类说明（接口类）：UserMemoryUnitOfWork
# 作用：定义长期记忆事务工作单元接口的能力契约，供应用层与具体实现解耦。
class UserMemoryUnitOfWork(Protocol):
    # 方法说明：memories
    # 作用：取得当前工作单元绑定的用户记忆仓储。
    # 入参：
    #   无显式入参。
    # 出参：UserMemoryRepository；当前事务内的长期记忆仓储。
    @property
    def memories(self) -> UserMemoryRepository: ...

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
    # 出参：'UserMemoryUnitOfWork'；长期记忆事务工作单元接口。
    def __enter__(self) -> "UserMemoryUnitOfWork": ...

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


UserMemoryUnitOfWorkFactory: TypeAlias = Callable[[], UserMemoryUnitOfWork]
