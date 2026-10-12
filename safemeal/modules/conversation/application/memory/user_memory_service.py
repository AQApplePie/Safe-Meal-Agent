"""协调用户长期记忆的读取、写入与归档。"""

from __future__ import annotations

from typing import List, Optional

from safemeal.modules.conversation.application.memory.memory_extraction import (
    UserMemoryExtractor,
)
from safemeal.modules.conversation.contracts.memory.extraction import MemoryCandidate
from safemeal.modules.conversation.ports.user_memory_repository import (
    UserMemoryUnitOfWorkFactory,
)
from safemeal.modules.conversation.contracts.memory.models import (
    UserMemoryCreate,
    UserMemoryRead,
    UserMemoryUpdate,
)
from safemeal.shared.types import JsonObject, to_json_object


# 类说明（业务或基础设施实现类）：UserMemoryService
# 作用：实现长期记忆管理与上下文服务，封装该组件的业务处理与依赖协作。
class UserMemoryService:
    # 方法说明：__init__
    # 作用：初始化长期记忆管理与上下文服务，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   uow_factory（UserMemoryUnitOfWorkFactory）：创建事务工作单元的工厂。
    #   extractor（UserMemoryExtractor | None）：用户消息记忆抽取器；默认值为 None。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(
        self,
        uow_factory: UserMemoryUnitOfWorkFactory,
        extractor: UserMemoryExtractor | None = None,
    ) -> None:
        # 实例属性说明：_uow_factory
        # 作用：创建事务工作单元的工厂。
        self._uow_factory = uow_factory
        # 实例属性说明：_extractor
        # 作用：用户消息记忆抽取器。
        self._extractor = extractor or UserMemoryExtractor()

    # 方法说明：remember_from_message
    # 作用：从当前用户消息提取并保存长期记忆候选。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   message（str）：本轮用户消息或问题文本。
    #   source_session_id（Optional[str]）：记忆或结果对应的来源会话标识；默认值为 None。
    #   source_message_id（Optional[str]）：记忆或结果对应的来源消息标识；默认值为 None。
    # 出参：List[UserMemoryRead]；长期记忆读取视图的集合。
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

    # 方法说明：_build_create_command
    # 作用：从聊天请求及用户消息组装助手消息的持久化创建命令。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   candidate（MemoryCandidate）：当前待筛选候选。
    #   source_session_id（Optional[str]）：记忆或结果对应的来源会话标识；默认值为 None。
    #   source_message_id（Optional[str]）：记忆或结果对应的来源消息标识；默认值为 None。
    # 出参：UserMemoryCreate；用户长期记忆创建命令。
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

    # 方法说明：list_memories
    # 作用：读取用户长期记忆并按状态、类型等条件过滤。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   include_archived（bool）：是否包含归档记忆；默认值为 False。
    #   limit（int）：本次查询或处理的最大条目数；默认值为 100。
    # 出参：List[UserMemoryRead]；长期记忆读取视图的集合。
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

    # 方法说明：load_agent_memories
    # 作用：按本轮需求读取可用于 Agent 的用户长期记忆。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   limit（int）：本次查询或处理的最大条目数；默认值为 50。
    # 出参：List[JsonObject]；JSON 字段映射的集合。
    def load_agent_memories(
        self,
        *,
        user_id: str,
        limit: int = 50,
    ) -> List[JsonObject]:
        with self._uow_factory() as uow:
            records = uow.memories.list_active_memories(user_id, limit=limit + 20)
            soft = [
                record
                for record in records
                if record.memory_type
                not in {
                    "conversation_episode",
                    "dietary_allergy",
                    "dietary_restriction",
                }
            ][:limit]
            hard = [
                record
                for kind in ("dietary_allergy", "dietary_restriction")
                for record in uow.memories.list_active_memories(
                    user_id, memory_type=kind, limit=None
                )
            ]
            records = list({record.id: record for record in [*hard, *soft]}.values())
            memory_ids = [int(record.id) for record in records]
            if memory_ids:
                uow.memories.mark_used(memory_ids)
                uow.commit()
            return [
                to_json_object(UserMemoryRead.model_validate(record))
                for record in records
            ]

    # 方法说明：load_agent_memories_by_types
    # 作用：按记忆类型加载本轮 Agent 上下文所需记忆。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   memory_types（set[str]）：允许加载或处理的长期记忆类型集合。
    #   limit（int）：本次查询或处理的最大条目数；默认值为 50。
    # 出参：List[JsonObject]；JSON 字段映射的集合。
    def load_agent_memories_by_types(
        self,
        *,
        user_id: str,
        memory_types: set[str],
        limit: int = 50,
    ) -> List[JsonObject]:

        if not memory_types:
            return []
        with self._uow_factory() as uow:
            records = []
            remaining = limit
            for memory_type in sorted(memory_types):
                if remaining <= 0:
                    break
                selected = uow.memories.list_active_memories(
                    user_id,
                    memory_type=memory_type,
                    limit=remaining,
                )
                records.extend(selected)
                remaining -= len(selected)
            memory_ids = [int(record.id) for record in records]
            if memory_ids:
                uow.memories.mark_used(memory_ids)
                uow.commit()
            return [
                to_json_object(UserMemoryRead.model_validate(record))
                for record in records
            ]

    # 方法说明：remember_episode
    # 作用：保存本次对话或任务摘要作为情景记忆。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   summary（str）：已生成的上下文或工具结果摘要。
    #   message_count（int）：当前上下文所需或已有的消息数量。
    # 出参：UserMemoryRead；长期记忆读取视图。
    def remember_episode(
        self,
        *,
        user_id: str,
        session_id: str,
        summary: str,
        message_count: int,
    ) -> UserMemoryRead:

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

    # 方法说明：load_episodic_memories
    # 作用：读取用户最近任务片段，供后续请求参考。
    # 入参：
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   limit（int）：本次查询或处理的最大条目数；默认值为 10。
    # 出参：List[JsonObject]；JSON 字段映射的集合。
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

    # 方法说明：create_memory
    # 作用：创建一条结构化长期记忆并绑定来源。
    # 入参：
    #   data（UserMemoryCreate）：用户长期记忆创建命令。
    # 出参：UserMemoryRead；长期记忆读取视图。
    def create_memory(self, data: UserMemoryCreate) -> UserMemoryRead:
        with self._uow_factory() as uow:
            record = uow.memories.upsert_memory(data)
            uow.commit()
            return UserMemoryRead.model_validate(record)

    # 方法说明：update_memory
    # 作用：更新归属当前用户的长期记忆字段。
    # 入参：
    #   memory_id（int）：长期记忆标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    #   data（UserMemoryUpdate）：长期记忆更新命令。
    # 出参：Optional[UserMemoryRead]；长期记忆读取视图或 None。
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

    # 方法说明：archive_memory
    # 作用：将指定长期记忆归档，保留历史记录而停止参与当前上下文。
    # 入参：
    #   memory_id（int）：长期记忆标识。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：Optional[UserMemoryRead]；长期记忆读取视图或 None。
    def archive_memory(self, memory_id: int, user_id: str) -> Optional[UserMemoryRead]:
        with self._uow_factory() as uow:
            record = uow.memories.archive_memory(memory_id, user_id)
            if record is not None:
                uow.commit()
                return UserMemoryRead.model_validate(record)
            return None
