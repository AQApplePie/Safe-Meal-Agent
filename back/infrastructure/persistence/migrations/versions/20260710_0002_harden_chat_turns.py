"""Harden chat ownership, ordering, and turn idempotency.

Revision ID: 20260710_0002
Revises: 20260705_0001
Create Date: 2026-07-10 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "20260710_0002"
down_revision: str | None = "20260705_0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # Historical anonymous rows receive distinct, non-empty owners before the
    # database constraint is tightened.
    sessions = sa.table(
        "chat_sessions",
        sa.column("id", sa.String(length=255)),
        sa.column("user_id", sa.String(length=255)),
        sa.column("next_message_order", sa.Integer()),
    )
    anonymous_ids = bind.execute(
        sa.select(sessions.c.id).where(sessions.c.user_id.is_(None))
    ).scalars()
    for session_id in anonymous_ids:
        legacy_user_id = f"legacy:{session_id}"[:255]
        bind.execute(
            sa.update(sessions)
            .where(sessions.c.id == session_id)
            .values(user_id=legacy_user_id)
        )

    op.alter_column(
        "chat_sessions",
        "user_id",
        existing_type=sa.String(length=255),
        nullable=False,
    )
    op.add_column(
        "chat_sessions",
        sa.Column(
            "next_message_order",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
            comment="Next unreserved message order within this session",
        ),
    )

    messages_for_order = sa.table(
        "chat_messages",
        sa.column("session_id", sa.String(length=255)),
        sa.column("order_index", sa.Integer()),
    )
    max_orders = bind.execute(
        sa.select(
            messages_for_order.c.session_id,
            sa.func.max(messages_for_order.c.order_index),
        ).group_by(messages_for_order.c.session_id)
    ).all()
    for session_id, max_order in max_orders:
        bind.execute(
            sa.update(sessions)
            .where(sessions.c.id == session_id)
            .values(next_message_order=int(max_order) + 1)
        )

    op.add_column(
        "chat_messages",
        sa.Column(
            "client_request_id",
            sa.String(length=255),
            nullable=True,
            comment="Client idempotency key scoped to the parent session",
        ),
    )
    op.add_column(
        "chat_messages",
        sa.Column(
            "reply_to_message_id",
            sa.Integer(),
            nullable=True,
            comment="User message answered by this response",
        ),
    )
    op.add_column(
        "chat_messages",
        sa.Column(
            "turn_status",
            sa.String(length=32),
            nullable=True,
            comment="User turn state: processing, completed, or failed",
        ),
    )
    op.add_column(
        "chat_messages",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
            comment="Last turn-state or response update timestamp",
        ),
    )
    op.create_foreign_key(
        "fk_chat_messages_reply_to_message",
        "chat_messages",
        "chat_messages",
        ["reply_to_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_chat_messages_session_request",
        "chat_messages",
        ["session_id", "client_request_id"],
    )
    op.create_unique_constraint(
        "uq_chat_messages_reply_to",
        "chat_messages",
        ["reply_to_message_id"],
    )
    op.create_check_constraint(
        "ck_chat_messages_turn_status",
        "chat_messages",
        "turn_status IS NULL OR turn_status IN ('processing', 'completed', 'failed')",
    )
    op.create_index(
        "ix_chat_messages_turn_status",
        "chat_messages",
        ["turn_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_turn_status", table_name="chat_messages")
    op.drop_constraint(
        "ck_chat_messages_turn_status",
        "chat_messages",
        type_="check",
    )
    op.drop_constraint(
        "uq_chat_messages_reply_to",
        "chat_messages",
        type_="unique",
    )
    op.drop_constraint(
        "uq_chat_messages_session_request",
        "chat_messages",
        type_="unique",
    )
    op.drop_constraint(
        "fk_chat_messages_reply_to_message",
        "chat_messages",
        type_="foreignkey",
    )
    op.drop_column("chat_messages", "updated_at")
    op.drop_column("chat_messages", "turn_status")
    op.drop_column("chat_messages", "reply_to_message_id")
    op.drop_column("chat_messages", "client_request_id")
    op.drop_column("chat_sessions", "next_message_order")
    op.alter_column(
        "chat_sessions",
        "user_id",
        existing_type=sa.String(length=255),
        nullable=True,
    )
