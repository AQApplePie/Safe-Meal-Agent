"""实现持久化基础设施适配。"""

from contextlib import contextmanager
from collections.abc import Callable
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

_database_url: str | None = None
_debug = False
_connect_timeout = 10
_lock_wait_timeout = 2
_engine: Engine | None = None


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


# 类说明（SQL 类）：Base
# 作用：提供 ORM 模型共用的声明基类与表元数据。
class Base(DeclarativeBase):
    pass


# 方法说明：configure_database
# 作用：配置并创建应用使用的 SQLAlchemy 引擎及会话工厂。
# 入参：
#   url（str）：当前外部资源或服务的连接地址。
#   debug（bool）：是否启用调试模式；默认值为 False。
#   connect_timeout（int）：建立外部连接的超时时长，单位秒；默认值为 10。
#   lock_wait_timeout（int）：数据库锁等待超时，单位秒；默认值为 2。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def configure_database(
    url: str,
    *,
    debug: bool = False,
    connect_timeout: int = 10,
    lock_wait_timeout: int = 2,
) -> None:
    global _database_url, _debug, _connect_timeout, _lock_wait_timeout
    if _engine is not None and url != _database_url:
        raise RuntimeError("Cannot reconfigure an active database engine")
    _database_url, _debug, _connect_timeout = url, debug, connect_timeout
    _lock_wait_timeout = lock_wait_timeout


# 方法说明：get_engine
# 作用：取得应用配置的全局 SQLAlchemy 引擎。
# 入参：
#   无显式入参。
# 出参：Engine；SQLAlchemy 引擎。
def get_engine() -> Engine:
    global _engine

    if _engine is None:
        if not _database_url:
            raise RuntimeError(
                "Database must be configured by application/service/composition"
            )
        options: dict[str, object] = {
            "echo": _debug,
            "future": True,
            "pool_pre_ping": True,
        }
        if _database_url.lower().startswith("mysql"):
            options.update(
                connect_args={
                    "connect_timeout": _connect_timeout,
                    "init_command": f"SET SESSION innodb_lock_wait_timeout={_lock_wait_timeout}",
                },
            )
        _engine = create_engine(_database_url, **options)
        SessionLocal.configure(bind=_engine)

    return _engine


# 方法说明：dispose_engine
# 作用：释放全局 SQLAlchemy 引擎的连接池资源。
# 入参：
#   无显式入参。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def dispose_engine() -> None:

    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
        SessionLocal.configure(bind=None)


# 方法说明：session_scope
# 作用：创建 SQL 会话上下文，正常退出时提交，异常时回滚并释放资源。
# 入参：
#   commit（bool）：本次操作是否提交事务；默认值为 True。
#   session_factory（Callable[[], Session] | None）：创建 SQLAlchemy 会话的工厂；默认值为
# None。
# 出参：Iterator[Session]；SQL 会话上下文；进入 with 块时取得会话，退出时处理提交或回滚。
@contextmanager
def session_scope(
    *,
    commit: bool = True,
    session_factory: Callable[[], Session] | None = None,
) -> Iterator[Session]:
    if session_factory is None:
        get_engine()
        session = SessionLocal()
    else:
        session = session_factory()
    try:
        yield session
        if commit:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
