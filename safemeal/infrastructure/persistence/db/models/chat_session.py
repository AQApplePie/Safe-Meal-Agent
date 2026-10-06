"""
用于持久存储对话的聊天会话模型。

轻量级用户 ID 系统——无需身份验证，仅用于用户识别。
"""

from sqlalchemy import Boolean, Column, DateTime, Integer, String, func, text
from sqlalchemy.orm import relationship

from safemeal.infrastructure.persistence.database import Base


class ChatSession(Base):
    """
    用于持久存储对话的聊天会话模型。

    采用轻量级用户 ID 系统：

    - user_id 是由前端提供的字符串（设备 ID、UUID 等）

    - 无需用户表或身份验证

    - 允许按用户分组会话，无需登录
    """

    __tablename__ = "chat_sessions"


    id = Column(String(255), primary_key=True, index=True, comment="Session UUID")


    user_id = Column(
        String(255),
        nullable=False,
        index=True,
        comment="User identifier (device ID, anonymous UUID, etc.) - no authentication",
    )


    title = Column(
        String(500),
        nullable=False,
        comment="Session title (usually derived from first query)",
    )


    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Session creation timestamp",
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
        comment="Last update timestamp",
    )


    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
        comment="Whether the session is active (soft delete flag)",
    )



    next_message_order = Column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
        comment="Next unreserved message order within this session",
    )


    messages = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.order_index",
    )

    def __repr__(self) -> str:
        return f"<ChatSession id={self.id} user_id={self.user_id} title={self.title[:30]!r}>"
