"""聊天会话的 SQL ORM 映射；访问权限由应用层认证身份和会话归属校验控制。"""

from sqlalchemy import Boolean, Column, DateTime, Integer, String, func, text
from sqlalchemy.orm import relationship

from safemeal.infrastructure.persistence.database import Base


# 类说明（SQL 类）：ChatSession
# 作用：定义聊天会话数据库模型的关系型表映射、字段和关联。
class ChatSession(Base):
    """SQL 类：保存会话所有者、标题、活动状态与下一消息顺序号。

    user_id 保存应用层由可信身份生成的存储主体，用于会话归属校验。
    会话与消息的关联在此声明，登录认证和授权判断由应用服务负责。
    """

    # 字段说明：__tablename__
    # 作用：SQL 类映射的数据库表名。
    # 初始值：'chat_sessions'。
    __tablename__ = "chat_sessions"


    # 字段说明：id
    # 作用：该业务记录的唯一标识，SQL 模型中通常对应主键。
    # 配置：主键标记=True；是否建立索引=True。
    id = Column(String(255), primary_key=True, index=True, comment="Session UUID")


    # 字段说明：user_id
    # 作用：经身份绑定后的持久化用户标识。
    # 配置：是否可为空=False；是否建立索引=True。
    user_id = Column(
        String(255),
        nullable=False,
        index=True,
        comment="User identifier (device ID, anonymous UUID, etc.) - no authentication",
    )


    # 字段说明：title
    # 作用：会话、文档或菜谱标题。
    # 配置：是否可为空=False。
    title = Column(
        String(500),
        nullable=False,
        comment="Session title (usually derived from first query)",
    )


    # 字段说明：created_at
    # 作用：记录创建时间，用于排序和审计。
    # 配置：是否可为空=False。
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Session creation timestamp",
    )
    # 字段说明：updated_at
    # 作用：记录最后更新时间。
    # 配置：是否可为空=True。
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
        comment="Last update timestamp",
    )


    # 字段说明：is_active
    # 作用：该记录或约束是否处于生效状态。
    # 配置：默认值=True；是否可为空=False。
    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
        comment="Whether the session is active (soft delete flag)",
    )



    # 字段说明：next_message_order
    # 作用：会话内下一条消息的顺序号。
    # 配置：是否可为空=False；默认值=1。
    next_message_order = Column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
        comment="Next unreserved message order within this session",
    )


    # 字段说明：messages
    # 作用：按顺序组织的历史对话消息。
    # 配置：关系反向属性='session'。
    messages = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.order_index",
    )

    # 方法说明：__repr__
    # 作用：生成包含关键标识的对象调试字符串，便于日志定位。
    # 入参：
    #   无显式入参。
    # 出参：str；包含对象关键标识的调试字符串。
    def __repr__(self) -> str:
        return f"<ChatSession id={self.id} user_id={self.user_id} title={self.title[:30]!r}>"
