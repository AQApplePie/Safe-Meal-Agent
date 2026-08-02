"""用户长期记忆 ORM 模型。

该表保存跨会话仍然有效的用户画像事实，例如过敏、忌口、口味偏好、
健康目标和烹饪条件。它和 chat_messages 分表，是为了避免把完整聊天记录
误当成长期记忆。
"""

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)

from safemeal.infrastructure.persistence.database import Base


class UserMemory(Base):
    """跨 session 的结构化用户记忆。"""

    __tablename__ = "user_memories"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "memory_type",
            "memory_key",
            "status",
            name="uq_user_memories_active_key",
        ),
        Index("ix_user_memories_user_type_status", "user_id", "memory_type", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, index=True, comment="用户标识。")
    memory_type = Column(
        String(64),
        nullable=False,
        index=True,
        comment="记忆类型，例如 dietary_allergy/taste_preference。",
    )
    memory_key = Column(
        String(255),
        nullable=False,
        index=True,
        comment="去重和检索用的短键，例如 花生/少辣/空气炸锅。",
    )
    memory_value = Column(Text, nullable=False, comment="面向 Agent 的可读记忆文本。")
    confidence = Column(Float, nullable=False, default=1.0, comment="记忆置信度。")
    source = Column(
        String(64),
        nullable=False,
        default="explicit_user_statement",
        comment="记忆来源。",
    )
    status = Column(
        String(32),
        nullable=False,
        default="active",
        index=True,
        comment="active/archived。",
    )
    source_session_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="产生记忆的会话 ID。",
    )
    source_message_id = Column(
        String(255),
        nullable=True,
        comment="产生记忆的消息 ID。",
    )
    memory_metadata = Column(
        JSON,
        nullable=True,
        comment="额外结构化信息。",
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
    )
    last_used_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="最近一次被注入 Agent 上下文的时间。",
    )

    def __repr__(self) -> str:
        return (
            "<UserMemory "
            f"id={self.id} user_id={self.user_id!r} "
            f"type={self.memory_type!r} key={self.memory_key!r}>"
        )
