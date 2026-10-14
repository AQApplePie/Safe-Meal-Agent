"""Add deduplicated recent recipe views. Revision 20261008_0009."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME

revision = "20261008_0009"
down_revision = "20261008_0008"
branch_labels = None
depends_on = None


# 方法说明：upgrade
# 作用：应用本版本数据库结构变更，推进 Alembic 迁移版本。
# 入参：
#   无显式入参。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def upgrade() -> None:
    schema = sa.inspect(op.get_bind())
    if "recipes" not in schema.get_table_names():
        raise RuntimeError("Import the recipe catalog before applying view history")
    if "recipe_view_history" in schema.get_table_names():
        raise RuntimeError(
            "Unexpected recipe_view_history table; review schema before migration"
        )
    op.create_table(
        "recipe_view_history",
        sa.Column(
            "tenant_id",
            sa.String(100, collation="utf8mb4_0900_bin").with_variant(
                sa.String(100), "sqlite"
            ),
            primary_key=True,
        ),
        sa.Column(
            "subject",
            sa.String(255, collation="utf8mb4_0900_bin").with_variant(
                sa.String(255), "sqlite"
            ),
            primary_key=True,
        ),
        sa.Column(
            "recipe_id",
            sa.Integer(),
            sa.ForeignKey("recipes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "last_viewed_at",
            sa.DateTime().with_variant(DATETIME(fsp=6), "mysql"),
            nullable=False,
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_recipe_history_recent",
        "recipe_view_history",
        ["tenant_id", "subject", "last_viewed_at", "recipe_id"],
    )
    op.create_index("ix_recipe_history_recipe", "recipe_view_history", ["recipe_id"])


# 方法说明：downgrade
# 作用：撤销本版本数据库结构变更，恢复上一迁移版本。
# 入参：
#   无显式入参。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def downgrade() -> None:
    op.drop_table("recipe_view_history")
