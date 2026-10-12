"""SQLAlchemy 实现的用户长期记忆仓储。"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from types import TracebackType
from typing import List, Optional, cast

from sqlalchemy import desc
from sqlalchemy.orm import Session

from safemeal.modules.conversation.contracts.memory.models import (
    UserMemoryCreate,
    UserMemoryUpdate,
)
from safemeal.modules.conversation.ports.user_memory_repository import (
    UserMemoryUnitOfWork,
)
from safemeal.infrastructure.persistence.database import session_scope
from safemeal.infrastructure.persistence.db.models import UserMemory


# 类说明（SQL 类）：SqlAlchemyUserMemoryRepository
# 作用：实现用户长期记忆 SQL 仓储的查询、写入或运行状态持久化。
class SqlAlchemyUserMemoryRepository:
    """使用关系型数据库保存结构化用户记忆。"""

    # 方法说明：__init__
    # 作用：初始化用户长期记忆 SQL 仓储，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   session（Session）：当前 SQL 会话或聊天会话对象。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, session: Session) -> None:
        # 实例属性说明：_session
        # 作用：当前 SQL 会话或聊天会话对象。
        self._session = session

    # 方法说明：upsert_memory
    # 作用：按 user_id/type/key/status 幂等写入记忆。
    # 入参：
    #   data（UserMemoryCreate）：用户长期记忆创建命令。
    # 出参：UserMemory；用户长期记忆数据库模型。
    def upsert_memory(self, data: UserMemoryCreate) -> UserMemory:
        """按 user_id/type/key/status 幂等写入记忆。

        同一用户重复说“我花生过敏”时，不创建多条重复记忆，而是刷新置信度、
        来源和更新时间。
        """

        entity = (
            self._session.query(UserMemory)
            .filter(
                UserMemory.user_id == data.user_id,
                UserMemory.memory_type == data.memory_type,
                UserMemory.memory_key == data.memory_key,
                UserMemory.status == "active",
            )
            .first()
        )
        payload = data.model_dump()
        if entity is None:
            entity = UserMemory(**payload, status="active")
            self._session.add(entity)
        else:
            for field, value in payload.items():
                setattr(entity, field, value)
            setattr(entity, "status", "active")
            setattr(entity, "updated_at", datetime.now(timezone.utc))
        self._session.flush()
        return entity

    # 方法说明：get_memory
    # 作用：读取指定用户记忆并校验归属。
    # 入参：
    #   memory_id（int）：长期记忆标识。
    # 出参：Optional[UserMemory]；用户长期记忆数据库模型或 None。
    def get_memory(self, memory_id: int) -> Optional[UserMemory]:
        return self._session.get(UserMemory, memory_id)

    # 方法说明：list_active_memories
    # 作用：列出当前用户的活动长期记忆。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   memory_type（Optional[str]）：长期记忆类型；默认值为 None。
    #   limit（int | None）：本次查询或处理的最大条目数；默认值为 50。
    # 出参：List[UserMemory]；用户长期记忆数据库模型的集合。
    def list_active_memories(
        self,
        user_id: str,
        *,
        memory_type: Optional[str] = None,
        limit: int | None = 50,
    ) -> List[UserMemory]:
        query = self._session.query(UserMemory).filter(
            UserMemory.user_id == user_id,
            UserMemory.status == "active",
        )
        if memory_type:
            query = query.filter(UserMemory.memory_type == memory_type)
        return (
            query.order_by(desc(UserMemory.confidence), desc(UserMemory.updated_at))
            .limit(limit)
            .all()
        )

    # 方法说明：list_memories
    # 作用：读取用户长期记忆并按状态、类型等条件过滤。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   include_archived（bool）：是否包含归档记忆；默认值为 False。
    #   limit（int）：本次查询或处理的最大条目数；默认值为 100。
    # 出参：List[UserMemory]；用户长期记忆数据库模型的集合。
    def list_memories(
        self,
        user_id: str,
        *,
        include_archived: bool = False,
        limit: int = 100,
    ) -> List[UserMemory]:
        query = self._session.query(UserMemory).filter(UserMemory.user_id == user_id)
        if not include_archived:
            query = query.filter(UserMemory.status == "active")
        return query.order_by(desc(UserMemory.updated_at)).limit(limit).all()

    # 方法说明：update_memory
    # 作用：更新归属当前用户的长期记忆字段。
    # 入参：
    #   memory_id（int）：长期记忆标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   data（UserMemoryUpdate）：长期记忆更新命令。
    # 出参：Optional[UserMemory]；用户长期记忆数据库模型或 None。
    def update_memory(
        self,
        memory_id: int,
        user_id: str,
        data: UserMemoryUpdate,
    ) -> Optional[UserMemory]:
        entity = self.get_memory(memory_id)
        if entity is None or entity.user_id != user_id:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(entity, field, value)
        setattr(entity, "updated_at", datetime.now(timezone.utc))
        self._session.flush()
        return entity

    # 方法说明：archive_memory
    # 作用：将指定长期记忆归档，保留历史记录而停止参与当前上下文。
    # 入参：
    #   memory_id（int）：长期记忆标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：Optional[UserMemory]；用户长期记忆数据库模型或 None。
    def archive_memory(self, memory_id: int, user_id: str) -> Optional[UserMemory]:
        entity = self.get_memory(memory_id)
        if entity is not None and entity.user_id == user_id:
            (
                self._session.query(UserMemory)
                .filter(
                    UserMemory.user_id == entity.user_id,
                    UserMemory.memory_type == entity.memory_type,
                    UserMemory.memory_key == entity.memory_key,
                    UserMemory.status == "archived",
                    UserMemory.id != entity.id,
                )
                .delete(synchronize_session=False)
            )
            setattr(entity, "status", "archived")
            setattr(entity, "updated_at", datetime.now(timezone.utc))
            self._session.flush()
            return entity
        return None

    # 方法说明：mark_used
    # 作用：更新记忆最近使用时间或使用统计。
    # 入参：
    #   memory_ids（List[int]）：待更新长期记忆标识集合。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def mark_used(self, memory_ids: List[int]) -> None:
        if not memory_ids:
            return
        (
            self._session.query(UserMemory)
            .filter(UserMemory.id.in_(memory_ids))
            .update(
                {"last_used_at": datetime.now(timezone.utc)},
                synchronize_session="fetch",
            )
        )
        self._session.flush()

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
    ) -> int:
        if not memory_keys:
            return 0

        (
            self._session.query(UserMemory)
            .filter(
                UserMemory.user_id == user_id,
                UserMemory.memory_type.in_(("dietary_allergy", "dietary_restriction")),
                UserMemory.memory_key.in_(memory_keys),
                UserMemory.status == "archived",
            )
            .delete(synchronize_session=False)
        )
        updated = (
            self._session.query(UserMemory)
            .filter(
                UserMemory.user_id == user_id,
                UserMemory.memory_type.in_(("dietary_allergy", "dietary_restriction")),
                UserMemory.memory_key.in_(memory_keys),
                UserMemory.status == "active",
            )
            .update(
                {"status": "archived", "updated_at": datetime.now(timezone.utc)},
                synchronize_session="fetch",
            )
        )
        self._session.flush()
        return int(updated or 0)


# 类说明（SQL 类）：SqlAlchemyUserMemoryUnitOfWork
# 作用：管理用户记忆 SQL 事务工作单元的会话、提交与回滚边界。
class SqlAlchemyUserMemoryUnitOfWork:
    # 方法说明：__init__
    # 作用：初始化用户记忆 SQL 事务工作单元，保存注入依赖并建立初始配置或运行状态。
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
        # 实例属性说明：_memories
        # 作用：已经加载的用户长期记忆。
        # 类型：SqlAlchemyUserMemoryRepository | None。
        # 初始值：None。
        self._memories: SqlAlchemyUserMemoryRepository | None = None

    # 方法说明：memories
    # 作用：取得当前工作单元绑定的用户记忆仓储。
    # 入参：
    #   无显式入参。
    # 出参：SqlAlchemyUserMemoryRepository；当前事务内的长期记忆仓储。
    @property
    def memories(self) -> SqlAlchemyUserMemoryRepository:
        if self._memories is None:
            raise RuntimeError("memory Unit of Work is not active")
        return self._memories

    # 方法说明：__enter__
    # 作用：进入工作单元并创建事务资源，供 with 块内的仓储操作共享。
    # 入参：
    #   无显式入参。
    # 出参：'SqlAlchemyUserMemoryUnitOfWork'；用户记忆 SQL 事务工作单元。
    def __enter__(self) -> "SqlAlchemyUserMemoryUnitOfWork":
        if self._scope is not None:
            raise RuntimeError("memory Unit of Work cannot be re-entered")
        scope = session_scope(commit=False, session_factory=self._session_factory)
        session = scope.__enter__()
        self._scope = scope
        self._session = session
        self._memories = SqlAlchemyUserMemoryRepository(session)
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
            raise RuntimeError("memory Unit of Work is not active")
        try:
            scope.__exit__(exc_type, exc_value, traceback)
        finally:
            self._scope = None
            self._session = None
            self._memories = None

    # 方法说明：_require_session
    # 作用：取得当前工作单元已打开的 SQLAlchemy 会话；事务未启用时抛错。
    # 入参：
    #   无显式入参。
    # 出参：Session；SQLAlchemy 会话。
    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("memory Unit of Work is not active")
        return self._session


# 方法说明：sqlalchemy_user_memory_unit_of_work
# 作用：创建用户记忆模块 SQL 事务工作单元上下文。
# 入参：
#   无显式入参。
# 出参：UserMemoryUnitOfWork；事务工作单元上下文；进入 with 块时取得对应事务和仓储能力。
def sqlalchemy_user_memory_unit_of_work() -> UserMemoryUnitOfWork:

    return cast(UserMemoryUnitOfWork, SqlAlchemyUserMemoryUnitOfWork())


__all__ = [
    "SqlAlchemyUserMemoryRepository",
    "SqlAlchemyUserMemoryUnitOfWork",
    "sqlalchemy_user_memory_unit_of_work",
]
