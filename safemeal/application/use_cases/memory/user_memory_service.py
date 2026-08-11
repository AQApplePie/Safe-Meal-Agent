"""User long-term-memory use cases."""

from __future__ import annotations

from typing import List, Optional

from safemeal.modules.user_memory.memory_extraction import UserMemoryExtractor
from safemeal.modules.user_memory.memory_models import MemoryCandidate
from safemeal.application.ports import UserMemoryUnitOfWorkFactory
from safemeal.shared.contracts.memory import (
    UserMemoryCreate,
    UserMemoryRead,
    UserMemoryUpdate,
)
from safemeal.shared.types import JsonObject, to_json_object


class UserMemoryService:
    """Coordinate memory extraction and persistence through an explicit UoW."""

    def __init__(
        self,
        uow_factory: UserMemoryUnitOfWorkFactory,
        extractor: UserMemoryExtractor | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._extractor = extractor or UserMemoryExtractor()

    def remember_from_message(
        self,
        *,
        user_id: str,
        message: str,
        source_session_id: Optional[str] = None,
        source_message_id: Optional[str] = None,
    ) -> List[UserMemoryRead]:
        extraction = self._extractor.extract(message)
        commands = [
            self._build_create_command(
                user_id=user_id,
                candidate=candidate,
                source_session_id=source_session_id,
                source_message_id=source_message_id,
            )
            for candidate in extraction.candidates
        ]
        if not commands and not extraction.retracted_dietary_keys:
            return []

        with self._uow_factory() as uow:
            uow.memories.archive_active_dietary_memories(
                user_id, list(extraction.retracted_dietary_keys)
            )
            records = [uow.memories.upsert_memory(command) for command in commands]
            uow.commit()
            return [UserMemoryRead.model_validate(record) for record in records]

    @staticmethod
    def _build_create_command(
        *,
        user_id: str,
        candidate: MemoryCandidate,
        source_session_id: Optional[str] = None,
        source_message_id: Optional[str] = None,
    ) -> UserMemoryCreate:
        return UserMemoryCreate(
            user_id=user_id,
            memory_type=candidate.memory_type,
            memory_key=candidate.key,
            memory_value=candidate.value,
            confidence=candidate.confidence,
            source="explicit_user_statement",
            source_session_id=source_session_id,
            source_message_id=source_message_id,
            memory_metadata=candidate.metadata,
        )

    def list_memories(
        self,
        *,
        user_id: str,
        include_archived: bool = False,
        limit: int = 100,
    ) -> List[UserMemoryRead]:
        with self._uow_factory() as uow:
            records = uow.memories.list_memories(
                user_id,
                include_archived=include_archived,
                limit=limit,
            )
            return [UserMemoryRead.model_validate(record) for record in records]

    def load_agent_memories(
        self,
        *,
        user_id: str,
        limit: int = 50,
    ) -> List[JsonObject]:
        with self._uow_factory() as uow:
            records = uow.memories.list_active_memories(user_id, limit=limit + 20)
            records = [
                record
                for record in records
                if record.memory_type != "conversation_episode"
            ][:limit]
            memory_ids = [int(record.id) for record in records]
            if memory_ids:
                uow.memories.mark_used(memory_ids)
                uow.commit()
            return [
                to_json_object(UserMemoryRead.model_validate(record))
                for record in records
            ]

    def remember_episode(
        self,
        *,
        user_id: str,
        session_id: str,
        summary: str,
        message_count: int,
    ) -> UserMemoryRead:
        """Persist the latest compacted summary for one conversation."""

        normalized = " ".join(summary.split())[:2_000]
        if not normalized:
            raise ValueError("episode summary cannot be blank")
        return self.create_memory(
            UserMemoryCreate(
                user_id=user_id,
                memory_type="conversation_episode",
                memory_key=session_id,
                memory_value=normalized,
                confidence=1.0,
                source="conversation_summary",
                source_session_id=session_id,
                memory_metadata={"message_count": max(0, message_count)},
            )
        )

    def load_episodic_memories(
        self,
        *,
        user_id: str,
        limit: int = 10,
    ) -> List[JsonObject]:
        with self._uow_factory() as uow:
            records = uow.memories.list_active_memories(
                user_id,
                memory_type="conversation_episode",
                limit=limit,
            )
            memory_ids = [int(record.id) for record in records]
            if memory_ids:
                uow.memories.mark_used(memory_ids)
                uow.commit()
            return [
                {
                    "id": record.id,
                    "memory_type": "conversation_episode",
                    "summary": record.memory_value,
                    "session_id": record.source_session_id,
                    "message_count": (record.memory_metadata or {}).get(
                        "message_count", 0
                    ),
                    "updated_at": (
                        record.updated_at.isoformat() if record.updated_at else None
                    ),
                }
                for record in records
            ]

    def create_memory(self, data: UserMemoryCreate) -> UserMemoryRead:
        with self._uow_factory() as uow:
            record = uow.memories.upsert_memory(data)
            uow.commit()
            return UserMemoryRead.model_validate(record)

    def update_memory(
        self,
        memory_id: int,
        user_id: str,
        data: UserMemoryUpdate,
    ) -> Optional[UserMemoryRead]:
        with self._uow_factory() as uow:
            record = uow.memories.update_memory(memory_id, user_id, data)
            if record is not None:
                uow.commit()
                return UserMemoryRead.model_validate(record)
            return None

    def archive_memory(self, memory_id: int, user_id: str) -> Optional[UserMemoryRead]:
        with self._uow_factory() as uow:
            record = uow.memories.archive_memory(memory_id, user_id)
            if record is not None:
                uow.commit()
                return UserMemoryRead.model_validate(record)
            return None
