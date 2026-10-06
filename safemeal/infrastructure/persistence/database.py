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
_engine: Engine | None = None


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


class Base(DeclarativeBase):
    pass


def configure_database(
    url: str, *, debug: bool = False, connect_timeout: int = 10
) -> None:
    global _database_url, _debug, _connect_timeout
    if _engine is not None and url != _database_url:
        raise RuntimeError("Cannot reconfigure an active database engine")
    _database_url, _debug, _connect_timeout = url, debug, connect_timeout


def get_engine() -> Engine:
    global _engine

    if _engine is None:
        if not _database_url:
            raise RuntimeError("Database must be configured by application/service/composition")
        options: dict[str, object] = {
            "echo": _debug,
            "future": True,
            "pool_pre_ping": True,
        }
        if _database_url.lower().startswith("mysql"):
            options.update(
                connect_args={"connect_timeout": _connect_timeout},
            )
        _engine = create_engine(_database_url, **options)
        SessionLocal.configure(bind=_engine)

    return _engine


def dispose_engine() -> None:

    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
        SessionLocal.configure(bind=None)


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
