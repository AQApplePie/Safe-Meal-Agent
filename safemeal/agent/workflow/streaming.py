"""管理请求范围内的回答与进度事件流。"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator
from safemeal.agent.contracts.workflow.stream import WorkflowProgress

_ANSWER_STREAM: ContextVar[asyncio.Queue[str | WorkflowProgress] | None] = ContextVar(
    "safemeal_answer_stream", default=None
)


def answer_stream_active() -> bool:
    return _ANSWER_STREAM.get() is not None


async def emit_answer_chunk(chunk: str) -> None:
    queue = _ANSWER_STREAM.get()
    if queue is not None and chunk:
        await queue.put(chunk)


@contextmanager
def use_answer_stream(queue: asyncio.Queue[str | WorkflowProgress]) -> Iterator[None]:
    token = _ANSWER_STREAM.set(queue)
    try:
        yield
    finally:
        _ANSWER_STREAM.reset(token)


@contextmanager
def suppress_answer_stream() -> Iterator[None]:
    token = _ANSWER_STREAM.set(None)
    try:
        yield
    finally:
        _ANSWER_STREAM.reset(token)


__all__ = ["answer_stream_active", "emit_answer_chunk", "use_answer_stream"]


_PROGRESS_STREAM: ContextVar[asyncio.Queue | None] = ContextVar(
    "workflow_progress_stream", default=None
)


@contextmanager
def use_progress_stream(queue: asyncio.Queue) -> Iterator[None]:
    token = _PROGRESS_STREAM.set(queue)
    try:
        yield
    finally:
        _PROGRESS_STREAM.reset(token)


async def emit_workflow_progress(stage: str, message: str) -> None:
    queue = _PROGRESS_STREAM.get()
    if queue is not None:
        await queue.put(WorkflowProgress(stage=stage, message=message))
