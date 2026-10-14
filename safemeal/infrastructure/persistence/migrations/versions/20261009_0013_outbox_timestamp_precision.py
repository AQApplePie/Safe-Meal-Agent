"""Preserve outbox deadlines and lease fencing at microsecond precision on MySQL."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME

revision = "20261009_0013"
down_revision = "20261008_0012"
branch_labels = None
depends_on = None

_COLUMNS = {
    "created_at": False,
    "available_at": False,
    "retry_at": False,
    "lease_until": True,
    "completed_at": True,
    "dead_at": True,
}


# 方法说明：upgrade
# 作用：应用本版本数据库结构变更，推进 Alembic 迁移版本。
# 入参：
#   无显式入参。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def upgrade() -> None:
    if op.get_bind().dialect.name != "mysql":
        return  # SQLite already preserves Python datetime microseconds.
    for column, nullable in _COLUMNS.items():
        op.alter_column(
            "behavior_outbox",
            column,
            existing_type=sa.DateTime(),
            type_=DATETIME(fsp=6),
            existing_nullable=nullable,
        )


# 方法说明：downgrade
# 作用：撤销本版本数据库结构变更，恢复上一迁移版本。
# 入参：
#   无显式入参。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def downgrade() -> None:
    if op.get_bind().dialect.name != "mysql":
        return
    for column, nullable in _COLUMNS.items():
        op.alter_column(
            "behavior_outbox",
            column,
            existing_type=DATETIME(fsp=6),
            type_=DATETIME(fsp=0),
            existing_nullable=nullable,
        )
