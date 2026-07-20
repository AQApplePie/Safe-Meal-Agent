"""Persist current answer-feedback state.

Revision ID: 20260716_0004
Revises: 20260713_0003
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "20260716_0004"
down_revision: str | None = "20260713_0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "answer_feedbacks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("rating", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("corrected_answer", sa.Text(), nullable=True),
        sa.Column(
            "review_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_required",
        ),
        sa.Column("review_sample_id", sa.String(length=64), nullable=True),
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
        sa.CheckConstraint(
            "rating IN ('positive', 'negative')",
            name="ck_answer_feedbacks_rating",
        ),
        sa.CheckConstraint(
            "review_status IN ('not_required', 'pending_queue', 'pending_review')",
            name="ck_answer_feedbacks_review_status",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["chat_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", name="uq_answer_feedbacks_message"),
    )
    op.create_index("ix_answer_feedbacks_id", "answer_feedbacks", ["id"])
    op.create_index(
        "ix_answer_feedbacks_session_id", "answer_feedbacks", ["session_id"]
    )
    op.create_index("ix_answer_feedbacks_user_id", "answer_feedbacks", ["user_id"])
    op.create_index("ix_answer_feedbacks_rating", "answer_feedbacks", ["rating"])
    op.create_index(
        "ix_answer_feedbacks_review_sample_id",
        "answer_feedbacks",
        ["review_sample_id"],
    )
    op.create_index(
        "ix_answer_feedbacks_user_rating",
        "answer_feedbacks",
        ["user_id", "rating"],
    )


def downgrade() -> None:
    op.drop_table("answer_feedbacks")
