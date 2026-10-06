"""删除旧版本地安装遗留的反馈表。

Revision ID: 20260802_0005
Revises: 20260716_0004
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect


revision: str = "20260802_0005"
down_revision: str | None = "20260716_0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    if inspect(op.get_bind()).has_table("answer_feedbacks"):
        op.drop_table("answer_feedbacks")


def downgrade() -> None:
    # 已下线的产品功能不在降级迁移中重新创建。
    pass
