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


# 类说明（SQL 类）：ChatMessage
# 作用：定义聊天消息数据库模型的关系型表映射、字段和关联。
class ChatMessage(Base):
    """SQL 类：保存聊天正文、来源与审批元数据，以及轮次处理状态。

    会话内顺序号、客户端请求标识和回复关联分别由唯一约束保护，
    供聊天用例处理请求重放、消息排序和同一用户消息的响应关联。
    """

    # 字段说明：__tablename__
    # 作用：SQL 类映射的数据库表名。
    # 初始值：'chat_messages'。
    __tablename__ = "chat_messages"
    # 字段说明：__table_args__
    # 作用：SQL 表级索引、唯一约束和检查约束，保障查询与数据一致性。
    #   唯一约束：这些列的组合不能重复；'session_id', 'order_index'；约束名='uq_chat_messages_session_order'。
    #   唯一约束：这些列的组合不能重复；'session_id', 'client_request_id'；约束名='uq_chat_messages_session_request'。
    #   唯一约束：这些列的组合不能重复；'reply_to_message_id'；约束名='uq_chat_messages_reply_to'。
    #   检查约束：行数据必须满足该表达式；"turn_status IS NULL OR turn_status IN ('processing', 'completed', 'failed')"；约束名='ck_chat_messages_turn_status'。
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


    # 字段说明：id
    # 作用：该业务记录的唯一标识，SQL 模型中通常对应主键。
    # 配置：主键标记=True；是否建立索引=True。
    id = Column(Integer, primary_key=True, index=True)


    # 字段说明：session_id
    # 作用：聊天会话或图检查点线程标识。
    # 配置：是否可为空=False；是否建立索引=True。
    session_id = Column(
        String(255),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent session ID",
    )


    # 字段说明：message_type
    # 作用：消息在对话流程中的业务类型。
    # 配置：是否可为空=False；是否建立索引=True。
    message_type = Column(
        String(50),
        nullable=False,
        index=True,
        comment="Message type: user_query, agent_response, knowledge, error, etc.",
    )


    # 字段说明：content
    # 作用：当前文件、消息或证据的正文内容。
    # 配置：是否可为空=False。
    content = Column(Text, nullable=False, comment="Message content text")


    # 字段说明：message_metadata
    # 作用：消息附属元数据，保存执行或来源信息。
    # 配置：是否可为空=True。
    message_metadata = Column(
        JSON,
        nullable=True,
        comment="Additional metadata: route info, confidence, sources, etc.",
    )


    # 字段说明：order_index
    # 作用：对象在当前列表或会话内的顺序位置。
    # 配置：是否可为空=False。
    order_index = Column(
        Integer, nullable=False, comment="Message order within the session"
    )



    # 字段说明：client_request_id
    # 作用：客户端提供的请求标识，用于识别同一请求并支持幂等处理。
    # 配置：是否可为空=True。
    client_request_id = Column(
        String(255),
        nullable=True,
        comment="Client idempotency key scoped to the parent session",
    )



    # 字段说明：reply_to_message_id
    # 作用：被当前回复关联的原始消息标识。
    # 配置：是否可为空=True。
    reply_to_message_id = Column(
        Integer,
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
        comment="User message answered by this response",
    )

    # 字段说明：turn_status
    # 作用：本轮对话或执行的最终状态。
    # 配置：是否可为空=True；是否建立索引=True。
    turn_status = Column(
        String(32),
        nullable=True,
        index=True,
        comment="User turn state: processing, completed, or failed",
    )


    # 字段说明：created_at
    # 作用：记录创建时间，用于排序和审计。
    # 配置：是否可为空=False。
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Message creation timestamp",
    )
    # 字段说明：updated_at
    # 作用：记录最后更新时间。
    # 配置：是否可为空=True。
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
        comment="Last turn-state or response update timestamp",
    )


    # 字段说明：session
    # 作用：当前 SQL 会话或聊天会话对象。
    # 配置：关系反向属性='messages'。
    session = relationship("ChatSession", back_populates="messages")

    # 方法说明：__repr__
    # 作用：生成包含关键标识的对象调试字符串，便于日志定位。
    # 入参：
    #   无显式入参。
    # 出参：str；包含对象关键标识的调试字符串。
    def __repr__(self) -> str:
        content_preview = self.content[:50] if self.content else ""
        return f"<ChatMessage id={self.id} type={self.message_type} content={content_preview!r}>"
