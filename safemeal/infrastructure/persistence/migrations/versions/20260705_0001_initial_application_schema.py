"""建立应用初始持久化结构。

Revision ID: 20260705_0001
Revises:
Create Date: 2026-07-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260705_0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


_LEGACY_APPLICATION_TABLES = {
    "chat_sessions",
    "chat_messages",
    "chat_history_snapshots",
}

_LEGACY_COLUMNS = {
    "chat_sessions": {
        "id",
        "user_id",
        "title",
        "created_at",
        "updated_at",
        "is_active",
    },
    "chat_messages": {
        "id",
        "session_id",
        "message_type",
        "content",
        "message_metadata",
        "order_index",
        "created_at",
    },
    "chat_history_snapshots": {
        "id",
        "session_id",
        "query",
        "response_data",
        "created_at",
    },
}

_LEGACY_INDEXES = {
    "chat_sessions": {
        "ix_chat_sessions_id",
        "ix_chat_sessions_user_id",
    },
    "chat_messages": {
        "ix_chat_messages_id",
        "ix_chat_messages_message_type",
        "ix_chat_messages_session_id",
        "uq_chat_messages_session_order",
    },
    "chat_history_snapshots": {
        "ix_chat_history_snapshots_id",
        "ix_chat_history_snapshots_session_id",
    },
}


def _is_reviewed_legacy_schema() -> bool:
    """识别唯一允许在保留数据前提下接管的未标记旧结构。

    新数据库和显式接管命令都会进入这里；如果旧结构不完整或已发生漂移，必须在
    执行任何结构变更前失败，迁移不会猜测修复方式。
    """

    bind = op.get_bind()
    schema = inspect(bind)
    existing = set(schema.get_table_names())
    application_tables = existing & (_LEGACY_APPLICATION_TABLES | {"user_memories"})
    if not application_tables:
        return False
    if application_tables != _LEGACY_APPLICATION_TABLES:
        raise RuntimeError(
            "unversioned application schema is partial or already modified; "
            f"found {sorted(application_tables)}"
        )

    for table_name in sorted(_LEGACY_APPLICATION_TABLES):
        columns = {column["name"] for column in schema.get_columns(table_name)}
        if columns != _LEGACY_COLUMNS[table_name]:
            raise RuntimeError(
                f"legacy table {table_name} has unexpected columns: "
                f"expected {sorted(_LEGACY_COLUMNS[table_name])}, found {sorted(columns)}"
            )

        indexes = {index["name"] for index in schema.get_indexes(table_name)}
        unique_constraints = {
            constraint["name"]
            for constraint in schema.get_unique_constraints(table_name)
            if constraint.get("name")
        }
        available = indexes | unique_constraints
        missing_indexes = _LEGACY_INDEXES[table_name] - available
        if missing_indexes:
            raise RuntimeError(
                f"legacy table {table_name} is missing indexes/constraints: "
                f"{sorted(missing_indexes)}"
            )

    for child in ("chat_messages", "chat_history_snapshots"):
        foreign_keys = schema.get_foreign_keys(child)
        if not any(
            foreign_key.get("referred_table") == "chat_sessions"
            and foreign_key.get("constrained_columns") == ["session_id"]
            and str(foreign_key.get("options", {}).get("ondelete", "")).upper()
            == "CASCADE"
            for foreign_key in foreign_keys
        ):
            raise RuntimeError(
                f"legacy table {child} is missing the reviewed chat_sessions CASCADE foreign key"
            )
    return True


def _create_legacy_application_tables() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(length=255), nullable=False, comment="Session UUID"),
        sa.Column(
            "user_id",
            sa.String(length=255),
            nullable=True,
            comment="User identifier (device ID, anonymous UUID, etc.) - no authentication",
        ),
        sa.Column(
            "title",
            sa.String(length=500),
            nullable=False,
            comment="Session title (usually derived from first query)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="Session creation timestamp",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="Last update timestamp",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            comment="Whether the session is active (soft delete flag)",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_sessions_id", "chat_sessions", ["id"], unique=False)
    op.create_index(
        "ix_chat_sessions_user_id", "chat_sessions", ["user_id"], unique=False
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "session_id",
            sa.String(length=255),
            nullable=False,
            comment="Parent session ID",
        ),
        sa.Column(
            "message_type",
            sa.String(length=50),
            nullable=False,
            comment="Message type: user_query, agent_response, knowledge, error, etc.",
        ),
        sa.Column("content", sa.Text(), nullable=False, comment="Message content text"),
        sa.Column(
            "message_metadata",
            sa.JSON(),
            nullable=True,
            comment="Additional metadata: route info, confidence, sources, etc.",
        ),
        sa.Column(
            "order_index",
            sa.Integer(),
            nullable=False,
            comment="Message order within the session",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="Message creation timestamp",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "order_index",
            name="uq_chat_messages_session_order",
        ),
    )
    op.create_index("ix_chat_messages_id", "chat_messages", ["id"], unique=False)
    op.create_index(
        "ix_chat_messages_message_type",
        "chat_messages",
        ["message_type"],
        unique=False,
    )
    op.create_index(
        "ix_chat_messages_session_id",
        "chat_messages",
        ["session_id"],
        unique=False,
    )

    op.create_table(
        "chat_history_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "session_id",
            sa.String(length=255),
            nullable=False,
            comment="Parent session ID",
        ),
        sa.Column("query", sa.Text(), nullable=False, comment="Original user query"),
        sa.Column(
            "response_data",
            sa.JSON(),
            nullable=False,
            comment="Complete response data including answer, metadata, sources, etc.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="Snapshot creation timestamp",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_history_snapshots_id",
        "chat_history_snapshots",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_chat_history_snapshots_session_id",
        "chat_history_snapshots",
        ["session_id"],
        unique=False,
    )


def _create_user_memories_table() -> None:
    op.create_table(
        "user_memories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id", sa.String(length=255), nullable=False, comment="用户标识。"
        ),
        sa.Column(
            "memory_type",
            sa.String(length=64),
            nullable=False,
            comment="记忆类型，例如 dietary_allergy/taste_preference。",
        ),
        sa.Column(
            "memory_key",
            sa.String(length=255),
            nullable=False,
            comment="去重和检索用的短键，例如 花生/少辣/空气炸锅。",
        ),
        sa.Column(
            "memory_value",
            sa.Text(),
            nullable=False,
            comment="面向 Agent 的可读记忆文本。",
        ),
        sa.Column("confidence", sa.Float(), nullable=False, comment="记忆置信度。"),
        sa.Column(
            "source",
            sa.String(length=64),
            nullable=False,
            comment="记忆来源。",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            comment="active/archived。",
        ),
        sa.Column(
            "source_session_id",
            sa.String(length=255),
            nullable=True,
            comment="产生记忆的会话 ID。",
        ),
        sa.Column(
            "source_message_id",
            sa.String(length=255),
            nullable=True,
            comment="产生记忆的消息 ID。",
        ),
        sa.Column(
            "memory_metadata", sa.JSON(), nullable=True, comment="额外结构化信息。"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="最近一次被注入 Agent 上下文的时间。",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "memory_type",
            "memory_key",
            "status",
            name="uq_user_memories_active_key",
        ),
    )
    op.create_index("ix_user_memories_id", "user_memories", ["id"], unique=False)
    op.create_index(
        "ix_user_memories_memory_key",
        "user_memories",
        ["memory_key"],
        unique=False,
    )
    op.create_index(
        "ix_user_memories_memory_type",
        "user_memories",
        ["memory_type"],
        unique=False,
    )
    op.create_index(
        "ix_user_memories_source_session_id",
        "user_memories",
        ["source_session_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_memories_status", "user_memories", ["status"], unique=False
    )
    op.create_index(
        "ix_user_memories_user_id", "user_memories", ["user_id"], unique=False
    )
    op.create_index(
        "ix_user_memories_user_type_status",
        "user_memories",
        ["user_id", "memory_type", "status"],
        unique=False,
    )


def upgrade() -> None:
    if not _is_reviewed_legacy_schema():
        _create_legacy_application_tables()
    _create_user_memories_table()


def downgrade() -> None:
    op.drop_index("ix_user_memories_user_type_status", table_name="user_memories")
    op.drop_index("ix_user_memories_user_id", table_name="user_memories")
    op.drop_index("ix_user_memories_status", table_name="user_memories")
    op.drop_index("ix_user_memories_source_session_id", table_name="user_memories")
    op.drop_index("ix_user_memories_memory_type", table_name="user_memories")
    op.drop_index("ix_user_memories_memory_key", table_name="user_memories")
    op.drop_index("ix_user_memories_id", table_name="user_memories")
    op.drop_table("user_memories")

    op.drop_index(
        "ix_chat_history_snapshots_session_id", table_name="chat_history_snapshots"
    )
    op.drop_index("ix_chat_history_snapshots_id", table_name="chat_history_snapshots")
    op.drop_table("chat_history_snapshots")

    op.drop_index("ix_chat_messages_session_id", table_name="chat_messages")
    op.drop_index("ix_chat_messages_message_type", table_name="chat_messages")
    op.drop_index("ix_chat_messages_id", table_name="chat_messages")
    op.drop_table("chat_messages")

    op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")
