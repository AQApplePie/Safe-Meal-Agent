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


# 类说明（SQL 类）：UserMemory
# 作用：定义用户长期记忆数据库模型的关系型表映射、字段和关联。
class UserMemory(Base):
    """跨 session 的结构化用户记忆。"""

    # 字段说明：__tablename__
    # 作用：SQL 类映射的数据库表名。
    # 初始值：'user_memories'。
    __tablename__ = "user_memories"
    # 字段说明：__table_args__
    # 作用：SQL 表级索引、唯一约束和检查约束，保障查询与数据一致性。
    #   唯一约束：这些列的组合不能重复；'user_id', 'memory_type', 'memory_key', 'status'；约束名='uq_user_memories_active_key'。
    #   索引：支持这些列的查询与排序；'ix_user_memories_user_type_status', 'user_id', 'memory_type', 'status'。
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

    # 字段说明：id
    # 作用：该业务记录的唯一标识，SQL 模型中通常对应主键。
    # 配置：主键标记=True；是否建立索引=True。
    id = Column(Integer, primary_key=True, index=True)
    # 字段说明：user_id
    # 作用：经身份绑定后的持久化用户标识。
    # 配置：是否可为空=False；是否建立索引=True。
    user_id = Column(String(255), nullable=False, index=True, comment="用户标识。")
    # 字段说明：memory_type
    # 作用：长期记忆类型。
    # 配置：是否可为空=False；是否建立索引=True。
    memory_type = Column(
        String(64),
        nullable=False,
        index=True,
        comment="记忆类型，例如 dietary_allergy/taste_preference。",
    )
    # 字段说明：memory_key
    # 作用：机器可读的长期记忆事实键。
    # 配置：是否可为空=False；是否建立索引=True。
    memory_key = Column(
        String(255),
        nullable=False,
        index=True,
        comment="去重和检索用的短键，例如 花生/少辣/空气炸锅。",
    )
    # 字段说明：memory_value
    # 作用：长期记忆的人类可读内容。
    # 配置：是否可为空=False。
    memory_value = Column(Text, nullable=False, comment="面向 Agent 的可读记忆文本。")
    # 字段说明：confidence
    # 作用：该记忆事实的置信度，范围为 0 至 1；显式安全约束仍按可信规则处理。
    # 配置：是否可为空=False；默认值=1.0。
    confidence = Column(Float, nullable=False, default=1.0, comment="记忆置信度。")
    # 字段说明：source
    # 作用：数据来源标识或提供该数据的对象。
    # 配置：是否可为空=False；默认值='explicit_user_statement'。
    source = Column(
        String(64),
        nullable=False,
        default="explicit_user_statement",
        comment="记忆来源。",
    )
    # 字段说明：status
    # 作用：HTTP 状态码或业务状态。
    # 配置：是否可为空=False；默认值='active'；是否建立索引=True。
    status = Column(
        String(32),
        nullable=False,
        default="active",
        index=True,
        comment="active/archived。",
    )
    # 字段说明：source_session_id
    # 作用：记忆或结果对应的来源会话标识。
    # 配置：是否可为空=True；是否建立索引=True。
    source_session_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="产生记忆的会话 ID。",
    )
    # 字段说明：source_message_id
    # 作用：记忆或结果对应的来源消息标识。
    # 配置：是否可为空=True。
    source_message_id = Column(
        String(255),
        nullable=True,
        comment="产生记忆的消息 ID。",
    )
    # 字段说明：memory_metadata
    # 作用：记忆的来源及辅助元数据。
    # 配置：是否可为空=True。
    memory_metadata = Column(
        JSON,
        nullable=True,
        comment="额外结构化信息。",
    )
    # 字段说明：created_at
    # 作用：记录创建时间，用于排序和审计。
    # 配置：是否可为空=False。
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    # 字段说明：updated_at
    # 作用：记录最后更新时间。
    # 配置：是否可为空=True。
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
    )
    # 字段说明：last_used_at
    # 作用：凭据或资源最近一次使用时间。
    # 配置：是否可为空=True。
    last_used_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="最近一次被注入 Agent 上下文的时间。",
    )

    # 方法说明：__repr__
    # 作用：生成包含关键标识的对象调试字符串，便于日志定位。
    # 入参：
    #   无显式入参。
    # 出参：str；包含对象关键标识的调试字符串。
    def __repr__(self) -> str:
        return (
            "<UserMemory "
            f"id={self.id} user_id={self.user_id!r} "
            f"type={self.memory_type!r} key={self.memory_key!r}>"
        )
