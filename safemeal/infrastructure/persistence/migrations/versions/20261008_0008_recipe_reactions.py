"""Add authenticated likes/favorites. Revision 20261008_0008."""

from alembic import op
import sqlalchemy as sa

revision = "20261008_0008"
down_revision = "20261008_0007"
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
        raise RuntimeError("Import the recipe catalog before applying reactions")
    if "recipe_reactions" in schema.get_table_names():
        raise RuntimeError(
            "Unexpected recipe_reactions table; review schema before migration"
        )
    op.create_table(
        "recipe_reactions",
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
        sa.Column("kind", sa.String(10), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "kind IN ('like', 'favorite')", name="ck_recipe_reactions_kind"
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index(
        "ix_recipe_reactions_counts",
        "recipe_reactions",
        ["tenant_id", "recipe_id", "kind"],
    )
    op.create_index("ix_recipe_reactions_recipe", "recipe_reactions", ["recipe_id"])


# 方法说明：downgrade
# 作用：撤销本版本数据库结构变更，恢复上一迁移版本。
# 入参：
#   无显式入参。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def downgrade() -> None:
    op.drop_table("recipe_reactions")
