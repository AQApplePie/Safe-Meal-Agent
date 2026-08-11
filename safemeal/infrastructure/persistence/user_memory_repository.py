"""SQLAlchemy 实现的用户长期记忆仓储。"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from types import TracebackType
from typing import List, Optional, cast

from sqlalchemy import desc
from sqlalchemy.orm import Session

from safemeal.shared.contracts.memory import (
    UserMemoryCreate,
    UserMemoryUpdate,
)
from safemeal.application.ports.persistence.user_memory_repository import (
    UserMemoryUnitOfWork,
)
from safemeal.infrastructure.persistence.database import session_scope
from safemeal.infrastructure.persistence.db.models import UserMemory


class SqlAlchemyUserMemoryRepository:
    """使用关系型数据库保存结构化用户记忆。"""

    def __init__(self, session: Session) -> None:
        self._session = session

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

    def get_memory(self, memory_id: int) -> Optional[UserMemory]:
        return self._session.get(UserMemory, memory_id)

    def list_active_memories(
        self,
        user_id: str,
        *,
        memory_type: Optional[str] = None,
        limit: int = 50,
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

    def archive_active_dietary_memories(
        self,
        user_id: str,
        memory_keys: List[str],
    ) -> int:
        if not memory_keys:
            return 0
        # The current schema keeps one archived snapshot per logical key. Remove an
        # older archived snapshot before moving a reactivated row back to archived,
        # otherwise the status-inclusive unique constraint would reject the update.
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


class SqlAlchemyUserMemoryUnitOfWork:
    """Own one Session and one explicit memory transaction."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._scope: AbstractContextManager[Session] | None = None
        self._session: Session | None = None
        self._memories: SqlAlchemyUserMemoryRepository | None = None

    @property
    def memories(self) -> SqlAlchemyUserMemoryRepository:
        if self._memories is None:
            raise RuntimeError("memory Unit of Work is not active")
        return self._memories

    def __enter__(self) -> "SqlAlchemyUserMemoryUnitOfWork":
        if self._scope is not None:
            raise RuntimeError("memory Unit of Work cannot be re-entered")
        scope = session_scope(commit=False, session_factory=self._session_factory)
        session = scope.__enter__()
        self._scope = scope
        self._session = session
        self._memories = SqlAlchemyUserMemoryRepository(session)
        return self

    def commit(self) -> None:
        self._require_session().commit()

    def rollback(self) -> None:
        self._require_session().rollback()

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

    def _require_session(self) -> Session:
        if self._session is None:
            raise RuntimeError("memory Unit of Work is not active")
        return self._session


def sqlalchemy_user_memory_unit_of_work() -> UserMemoryUnitOfWork:
    """Create a Unit of Work using the process-configured Session factory."""

    return cast(UserMemoryUnitOfWork, SqlAlchemyUserMemoryUnitOfWork())


__all__ = [
    "SqlAlchemyUserMemoryRepository",
    "SqlAlchemyUserMemoryUnitOfWork",
    "sqlalchemy_user_memory_unit_of_work",
]
