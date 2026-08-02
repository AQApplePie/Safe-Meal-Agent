"""Request-scoped answer token stream used by the SSE transport."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_ANSWER_STREAM: ContextVar[asyncio.Queue[str] | None] = ContextVar(
    "safemeal_answer_stream", default=None
)


def answer_stream_active() -> bool:
    return _ANSWER_STREAM.get() is not None


async def emit_answer_chunk(chunk: str) -> None:
    queue = _ANSWER_STREAM.get()
    if queue is not None and chunk:
        await queue.put(chunk)


@contextmanager
def use_answer_stream(queue: asyncio.Queue[str]) -> Iterator[None]:
    token = _ANSWER_STREAM.set(queue)
    try:
        yield
    finally:
        _ANSWER_STREAM.reset(token)


__all__ = ["answer_stream_active", "emit_answer_chunk", "use_answer_stream"]
