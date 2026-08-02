"""Remove the unused chat snapshot persistence slice.

Revision ID: 20260713_0003
Revises: 20260710_0002
Create Date: 2026-07-13 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "20260713_0003"
down_revision: str | None = "20260710_0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    bind = op.get_bind()
    count = int(
        bind.execute(
            sa.text("SELECT COUNT(*) FROM chat_history_snapshots")
        ).scalar_one()
    )
    if count:
        raise RuntimeError(
            "chat_history_snapshots is not empty; export and migrate its data before upgrading"
        )
    op.drop_table("chat_history_snapshots")


def downgrade() -> None:
    op.create_table(
        "chat_history_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("response_data", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
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
