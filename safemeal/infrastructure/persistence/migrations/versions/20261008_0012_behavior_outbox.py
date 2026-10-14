"""Transactional behavior outbox, durable retry and deduplication."""

from alembic import op
import sqlalchemy as sa

revision = "20261008_0012"
down_revision = "20261008_0011"
branch_labels = None
depends_on = None


# 方法说明：upgrade
# 作用：应用本版本数据库结构变更，推进 Alembic 迁移版本。
# 入参：
#   无显式入参。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def upgrade() -> None:
    schema = sa.inspect(op.get_bind())
    if not {"recipe_reactions", "recipe_view_history"} <= set(schema.get_table_names()):
        raise RuntimeError("Apply behavior migrations before outbox")
    if "behavior_outbox" in schema.get_table_names():
        raise RuntimeError("Unexpected outbox table; review schema before migration")
    op.create_table(
        "behavior_outbox",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("recipe_id", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("enabled", sa.Integer),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("available_at", sa.DateTime, nullable=False),
        sa.Column("retry_at", sa.DateTime, nullable=False),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_until", sa.DateTime),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("completed_at", sa.DateTime),
        sa.Column("dead_at", sa.DateTime),
        sa.Column("last_error", sa.Text),
    )
    op.create_index(
        "ix_behavior_outbox_delivery",
        "behavior_outbox",
        ["completed_at", "dead_at", "available_at"],
    )


# 方法说明：downgrade
# 作用：撤销本版本数据库结构变更，恢复上一迁移版本。
# 入参：
#   无显式入参。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def downgrade() -> None:
    op.drop_table("behavior_outbox")
