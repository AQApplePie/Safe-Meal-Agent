"""Request correlation propagated across HTTP, Agent, model and tool tasks."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator


_REQUEST_ID: ContextVar[str] = ContextVar("safemeal_request_id", default="-")


def current_request_id() -> str:
    return _REQUEST_ID.get()


@contextmanager
def use_request_id(request_id: str) -> Iterator[None]:
    token = _REQUEST_ID.set(request_id)
    try:
        yield
    finally:
        _REQUEST_ID.reset(token)


__all__ = ["current_request_id", "use_request_id"]
