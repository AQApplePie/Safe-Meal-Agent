"""Application database configuration and session utilities."""

from contextlib import contextmanager
from collections.abc import Callable
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from SafeMealAgent.back.config.settings import settings

_DEFAULT_LOG_ECHO = bool(settings.DEBUG)
_engine: Engine | None = None


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


class Base(DeclarativeBase):
    pass


def get_engine() -> Engine:
    """Return the application database engine, creating it on first use."""
    global _engine

    if _engine is None:
        options: dict[str, object] = {
            "echo": _DEFAULT_LOG_ECHO,
            "future": True,
            "pool_pre_ping": True,
        }
        if settings.DATABASE_URL.lower().startswith("mysql"):
            options.update(
                pool_size=settings.DB_POOL_SIZE,
                max_overflow=settings.DB_MAX_OVERFLOW,
                pool_timeout=settings.DB_POOL_TIMEOUT,
                pool_recycle=settings.DB_POOL_RECYCLE,
                connect_args={"connect_timeout": settings.DB_CONNECT_TIMEOUT},
            )
        _engine = create_engine(settings.DATABASE_URL, **options)
        SessionLocal.configure(bind=_engine)

    return _engine


def dispose_engine() -> None:
    """Dispose the process-scoped connection pool during application shutdown."""

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
    """
    Own one Session lifecycle and handle commit/rollback automatically.

    ``session_factory`` is injectable so Unit-of-Work tests can use an isolated
    engine without mutating the process-global ``SessionLocal`` binding. Set
    ``commit=False`` when an explicit Unit of Work owns the commit decision;
    exceptional exit still rolls back and every exit closes the Session.
    """
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
