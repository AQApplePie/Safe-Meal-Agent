"""
用于在会话中存储单个消息的聊天消息模型。
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from safemeal.infrastructure.persistence.database import Base


class ChatMessage(Base):
    """
    用于在会话中存储单个消息的聊天消息模型。

    存储结构化消息数据，包括用户查询、客服回复、

    SQL 查询、可视化图表和其他消息类型。
    """

    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "order_index",
            name="uq_chat_messages_session_order",
        ),
        UniqueConstraint(
            "session_id",
            "client_request_id",
            name="uq_chat_messages_session_request",
        ),
        UniqueConstraint(
            "reply_to_message_id",
            name="uq_chat_messages_reply_to",
        ),
        CheckConstraint(
            "turn_status IS NULL OR turn_status IN ('processing', 'completed', 'failed')",
            name="ck_chat_messages_turn_status",
        ),
    )

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Session relationship
    session_id = Column(
        String(255),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent session ID",
    )

    # Message type classification
    message_type = Column(
        String(50),
        nullable=False,
        index=True,
        comment="Message type: user_query, agent_response, knowledge, error, etc.",
    )

    # Message content
    content = Column(Text, nullable=False, comment="Message content text")

    # Additional metadata (flexible JSON storage)
    message_metadata = Column(
        JSON,
        nullable=True,
        comment="Additional metadata: route info, confidence, sources, etc.",
    )

    # Message ordering within session
    order_index = Column(
        Integer, nullable=False, comment="Message order within the session"
    )

    # Idempotency key supplied by the client. Only user messages populate it;
    # SQL unique constraints permit multiple NULL values.
    client_request_id = Column(
        String(255),
        nullable=True,
        comment="Client idempotency key scoped to the parent session",
    )

    # Stable association between a user question and its reserved response
    # position. It also prevents duplicate responses for one turn.
    reply_to_message_id = Column(
        Integer,
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
        comment="User message answered by this response",
    )

    turn_status = Column(
        String(32),
        nullable=True,
        index=True,
        comment="User turn state: processing, completed, or failed",
    )

    # Timestamp
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Message creation timestamp",
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
        comment="Last turn-state or response update timestamp",
    )

    # Relationships
    session = relationship("ChatSession", back_populates="messages")

    def __repr__(self) -> str:
        content_preview = self.content[:50] if self.content else ""
        return f"<ChatMessage id={self.id} type={self.message_type} content={content_preview!r}>"
