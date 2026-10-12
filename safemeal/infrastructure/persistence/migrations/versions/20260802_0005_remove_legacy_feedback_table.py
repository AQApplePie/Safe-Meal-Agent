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


# 方法说明：upgrade
# 作用：应用本版本数据库结构变更，推进 Alembic 迁移版本。
# 入参：
#   无显式入参。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def upgrade() -> None:
    if inspect(op.get_bind()).has_table("answer_feedbacks"):
        op.drop_table("answer_feedbacks")


# 方法说明：downgrade
# 作用：撤销本版本数据库结构变更，恢复上一迁移版本。
# 入参：
#   无显式入参。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def downgrade() -> None:
    # 已下线的产品功能不在降级迁移中重新创建。
    pass
