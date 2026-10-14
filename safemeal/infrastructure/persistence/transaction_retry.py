"""Retry only rolled-back MySQL lock conflicts, rebuilding the whole transaction."""

from collections.abc import Callable
from random import uniform
from time import sleep
from typing import TypeVar
from loguru import logger
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import OperationalError

T = TypeVar("T")
_LOCK_CONFLICTS = {1205, 1213}


# 方法说明：run_transaction
# 作用：为完整 SQL 事务提供有限的锁错误重试，并保持原子提交。
# 入参：
#   engine（Engine）：SQLAlchemy 数据库引擎。
#   operation（Callable[[Connection], T]）：需要在完整数据库事务中执行的函数。
#   max_attempts（int）：完整数据库事务最多尝试次数；默认值为 3。
# 出参：T；由泛型调用约定决定的结果。
def run_transaction(
    engine: Engine, operation: Callable[[Connection], T], *, max_attempts: int = 3
) -> T:
    if not 1 <= max_attempts <= 5:
        raise ValueError("Transaction attempts must be between 1 and 5")
    for attempt in range(1, max_attempts + 1):
        try:
            with engine.begin() as connection:
                return operation(connection)
        except OperationalError as exc:
            args = getattr(exc.orig, "args", ())
            code = args[0] if args else None
            if (
                engine.dialect.name != "mysql"
                or code not in _LOCK_CONFLICTS
                or attempt == max_attempts
            ):
                raise
            # engine.begin() has rolled back before retrying. Never replay a
            # connection/commit failure with an ambiguous outcome.
            logger.warning(
                "database.transaction.lock_retry code={} attempt={}", code, attempt
            )
            sleep(uniform(0.005, 0.015) * 2 ** (attempt - 1))
    raise AssertionError("Unreachable transaction retry state")
