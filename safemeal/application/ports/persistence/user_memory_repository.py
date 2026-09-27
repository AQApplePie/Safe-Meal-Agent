"""用户长期记忆仓储端口。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from types import TracebackType
from typing import List, Optional, Protocol, TypeAlias

from safemeal.application.contracts.memory.models import (
    UserMemoryCreate,
    UserMemoryUpdate,
)
from safemeal.shared.types import JsonObject


class UserMemoryRecord(Protocol):
    """仓储返回的用户记忆记录结构。

    该协议只描述应用层实际需要读取的字段，不绑定 SQLAlchemy ORM 类。
    """

    id: int
    user_id: str
    memory_type: str
    memory_key: str
    memory_value: str
    confidence: float
    source: str
    status: str
    source_session_id: Optional[str]
    source_message_id: Optional[str]
    memory_metadata: Optional[JsonObject]
    created_at: datetime
    updated_at: Optional[datetime]
    last_used_at: Optional[datetime]


class UserMemoryRepository(Protocol):
    """应用层依赖的用户记忆仓储接口，由基础设施层实现。"""

    def upsert_memory(self, data: UserMemoryCreate) -> UserMemoryRecord: ...

    def get_memory(self, memory_id: int) -> Optional[UserMemoryRecord]: ...

    def list_active_memories(
        self,
        user_id: str,
        *,
        memory_type: Optional[str] = None,
        limit: int | None = 50,
    ) -> List[UserMemoryRecord]: ...

    def list_memories(
        self,
        user_id: str,
        *,
        include_archived: bool = False,
        limit: int = 100,
    ) -> List[UserMemoryRecord]: ...

    def update_memory(
        self,
        memory_id: int,
        user_id: str,
        data: UserMemoryUpdate,
    ) -> Optional[UserMemoryRecord]: ...

    def archive_memory(
        self,
        memory_id: int,
        user_id: str,
    ) -> Optional[UserMemoryRecord]: ...

    def mark_used(self, memory_ids: List[int]) -> None: ...

    def archive_active_dietary_memories(
        self,
        user_id: str,
        memory_keys: List[str],
    ) -> int: ...


class UserMemoryUnitOfWork(Protocol):
    """One memory transaction and the persistence participating in it."""

    @property
    def memories(self) -> UserMemoryRepository: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def __enter__(self) -> "UserMemoryUnitOfWork": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


UserMemoryUnitOfWorkFactory: TypeAlias = Callable[[], UserMemoryUnitOfWork]
