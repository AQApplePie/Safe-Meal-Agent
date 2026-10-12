"""功能移除后继续保留旧本地结构的版本定位能力。

Revision ID: 20260716_0004
Revises: 20260713_0003
"""

from __future__ import annotations


revision: str = "20260716_0004"
down_revision: str | None = "20260713_0003"
branch_labels: str | None = None
depends_on: str | None = None


# 方法说明：upgrade
# 作用：应用本版本数据库结构变更，推进 Alembic 迁移版本。
# 入参：
#   无显式入参。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def upgrade() -> None:
    pass


# 方法说明：downgrade
# 作用：撤销本版本数据库结构变更，恢复上一迁移版本。
# 入参：
#   无显式入参。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def downgrade() -> None:
    pass
