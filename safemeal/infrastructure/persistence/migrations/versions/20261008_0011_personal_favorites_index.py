"""Add personal favorites ordering index. Revision 20261008_0011."""

from alembic import op
import sqlalchemy as sa

revision = "20261008_0011"
down_revision = "20261008_0010"
branch_labels = None
depends_on = None


# 方法说明：upgrade
# 作用：应用本版本数据库结构变更，推进 Alembic 迁移版本。
# 入参：
#   无显式入参。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def upgrade() -> None:
    schema = sa.inspect(op.get_bind())
    if "recipe_reactions" not in schema.get_table_names():
        raise RuntimeError("Apply recipe reactions migration before favorites index")
    if "ix_recipe_reactions_favorites" in {
        item["name"] for item in schema.get_indexes("recipe_reactions")
    }:
        raise RuntimeError("Unexpected favorites index; review schema before migration")
    op.create_index(
        "ix_recipe_reactions_favorites",
        "recipe_reactions",
        ["tenant_id", "subject", "kind", "created_at", "recipe_id"],
    )


# 方法说明：downgrade
# 作用：撤销本版本数据库结构变更，恢复上一迁移版本。
# 入参：
#   无显式入参。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def downgrade() -> None:
    op.drop_index("ix_recipe_reactions_favorites", table_name="recipe_reactions")
