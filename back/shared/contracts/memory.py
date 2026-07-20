"""Memory Service 跨服务契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional, Protocol, Sequence, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from SafeMealAgent.back.shared.types import JsonObject


MemoryType: TypeAlias = Literal[
    "dietary_allergy",
    "dietary_restriction",
    "taste_dislike",
    "taste_preference",
    "cooking_constraint",
    "cooking_equipment",
    "cooking_time",
    "health_goal",
]
MemoryStatus: TypeAlias = Literal["active", "archived"]
MemorySource: TypeAlias = Literal["explicit_user_statement", "manual"]


class UserMemoryCreate(BaseModel):
    """创建或更新一条用户长期记忆。"""

    user_id: str = Field(..., min_length=1, max_length=255, description="用户标识。")
    memory_type: MemoryType = Field(..., description="记忆类型。")
    memory_key: str = Field(
        ..., min_length=1, max_length=255, description="用于去重和检索的记忆键。"
    )
    memory_value: str = Field(
        ..., min_length=1, max_length=1_000, description="可展示给 Agent 的记忆内容。"
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="记忆置信度；显式过敏/忌口通常接近 1。",
    )
    source: MemorySource = Field(
        default="explicit_user_statement",
        description="记忆来源，例如 explicit_user_statement/manual。",
    )
    source_session_id: Optional[str] = Field(
        default=None,
        max_length=255,
        description="产生这条记忆的会话 ID。",
    )
    source_message_id: Optional[str] = Field(
        default=None,
        max_length=255,
        description="产生这条记忆的消息 ID；没有时可为空。",
    )
    memory_metadata: Optional[JsonObject] = Field(
        default=None,
        description="额外结构化信息，例如禁忌食材展开、抽取规则版本等。",
    )


class UserMemoryUpdate(BaseModel):
    """更新一条用户长期记忆。"""

    memory_value: Optional[str] = Field(default=None, min_length=1, max_length=1_000)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    status: Optional[MemoryStatus] = Field(
        default=None, description="active/archived。"
    )
    memory_metadata: Optional[JsonObject] = None


class UserMemoryRead(BaseModel):
    """读取用户长期记忆时返回的稳定视图。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    memory_type: MemoryType
    memory_key: str
    memory_value: str
    confidence: float
    source: MemorySource
    status: MemoryStatus
    source_session_id: Optional[str] = None
    source_message_id: Optional[str] = None
    memory_metadata: Optional[JsonObject] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None


class AgentMemoryProvider(Protocol):
    """Agent Orchestrator 依赖的最小记忆能力。

    本协议故意不暴露 Memory Service 的仓储、事务或完整 CRUD，只描述
    Orchestrator 在一次对话中需要的两个能力。
    """

    def remember_from_message(
        self,
        *,
        user_id: str,
        message: str,
        source_session_id: Optional[str] = None,
        source_message_id: Optional[str] = None,
    ) -> Sequence[UserMemoryRead | JsonObject]: ...

    def load_agent_memories(
        self,
        *,
        user_id: str,
        limit: int = 50,
    ) -> list[JsonObject]: ...
