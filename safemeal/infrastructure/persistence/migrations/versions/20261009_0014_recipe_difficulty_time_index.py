"""Support combined difficulty/time filtering without widening API contracts."""

from alembic import op
import sqlalchemy as sa

revision = "20261009_0014"
down_revision = "20261009_0013"
branch_labels = None
depends_on = None
NAME = "ix_recipe_browse_difficulty_time_id"


# 方法说明：upgrade
# 作用：应用本版本数据库结构变更，推进 Alembic 迁移版本。
# 入参：
#   无显式入参。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def upgrade() -> None:
    schema = sa.inspect(op.get_bind())
    if "recipes" not in schema.get_table_names():
        raise RuntimeError("Import the recipe catalog before applying browse indexes")
    if NAME in {index["name"] for index in schema.get_indexes("recipes")}:
        raise RuntimeError("Unexpected existing difficulty/time index; review schema")
    op.create_index(NAME, "recipes", ["difficulty", "total_time", "id"], unique=False)


# 方法说明：downgrade
# 作用：撤销本版本数据库结构变更，恢复上一迁移版本。
# 入参：
#   无显式入参。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def downgrade() -> None:
    op.drop_index(NAME, table_name="recipes")
