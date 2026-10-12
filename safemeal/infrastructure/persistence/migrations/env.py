"""应用持久化数据库的 Alembic 迁移环境。"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import os
from safemeal.config.platform import PlatformSettings
from safemeal.infrastructure.persistence.database import Base

# 导入模型模块，确保自动生成迁移时基础元数据已经完整注册。
import safemeal.infrastructure.persistence.db.models  # noqa: F401


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# 方法说明：_database_url
# 作用：解析迁移运行所需的数据库连接地址。
# 入参：
#   无显式入参。
# 出参：str；迁移运行使用的数据库连接地址。
def _database_url() -> str:
    return PlatformSettings(
        _env_file=os.environ.get("SAFEMEAL_ENV_FILE", ".env")
    ).DATABASE_URL


# 方法说明：run_migrations_offline
# 作用：不创建数据库引擎，直接按连接地址运行离线迁移。
# 入参：
#   无显式入参。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def run_migrations_offline() -> None:
    """不创建数据库引擎，直接按连接地址运行离线迁移。"""

    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# 方法说明：run_migrations_online
# 作用：通过真实数据库连接运行在线迁移。
# 入参：
#   无显式入参。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def run_migrations_online() -> None:
    """通过真实数据库连接运行在线迁移。"""

    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
