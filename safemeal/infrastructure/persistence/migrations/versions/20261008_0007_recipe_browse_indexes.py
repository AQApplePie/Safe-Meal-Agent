"""Add bounded recipe browsing indexes without rewriting existing migrations.

Revision ID: 20261008_0007
Revises: 20261001_0006
"""

from alembic import op
import sqlalchemy as sa

revision = "20261008_0007"
down_revision = "20261001_0006"
branch_labels = None
depends_on = None

# Name/cuisine and child relation indexes already exist in init_mysql.sql.
INDEXES = (
    ("recipes", "ix_recipe_browse_time_id", ("total_time", "id")),
    ("recipes", "ix_recipe_browse_calories_id", ("total_calories", "id")),
    ("recipes", "ix_recipe_browse_difficulty_name_id", ("difficulty", "name", "id")),
)


# 方法说明：upgrade
# 作用：应用本版本数据库结构变更，推进 Alembic 迁移版本。
# 入参：
#   无显式入参。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def upgrade() -> None:
    schema = sa.inspect(op.get_bind())
    if "recipes" not in schema.get_table_names():
        raise RuntimeError(
            "Import the recipe catalog schema before applying recipe browse indexes"
        )
    existing = {index["name"] for index in schema.get_indexes("recipes")}
    conflicts = {name for _, name, _ in INDEXES} & existing
    if conflicts:
        raise RuntimeError(
            f"Unexpected existing indexes: {sorted(conflicts)}; review schema before migration"
        )
    for table, name, columns in INDEXES:
        op.create_index(name, table, list(columns), unique=False)


# 方法说明：downgrade
# 作用：撤销本版本数据库结构变更，恢复上一迁移版本。
# 入参：
#   无显式入参。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def downgrade() -> None:
    for table, name, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
