"""Add tenant/day aggregation index. Revision 20261008_0010."""

from alembic import op
import sqlalchemy as sa

revision = "20261008_0010"
down_revision = "20261008_0009"
branch_labels = None
depends_on = None


# 方法说明：upgrade
# 作用：应用本版本数据库结构变更，推进 Alembic 迁移版本。
# 入参：
#   无显式入参。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def upgrade() -> None:
    schema = sa.inspect(op.get_bind())
    if "recipe_view_history" not in schema.get_table_names():
        raise RuntimeError("Apply recipe view history migration before ranking index")
    if "ix_recipe_history_ranking_day" in {
        item["name"] for item in schema.get_indexes("recipe_view_history")
    }:
        raise RuntimeError("Unexpected ranking index; review schema before migration")
    op.create_index(
        "ix_recipe_history_ranking_day",
        "recipe_view_history",
        ["tenant_id", "last_viewed_at", "recipe_id"],
    )


# 方法说明：downgrade
# 作用：撤销本版本数据库结构变更，恢复上一迁移版本。
# 入参：
#   无显式入参。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def downgrade() -> None:
    op.drop_index("ix_recipe_history_ranking_day", table_name="recipe_view_history")
