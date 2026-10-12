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


# 方法说明：answer_stream_active
# 作用：判断当前请求是否启用了答案流输出。
# 入参：
#   无显式入参。
# 出参：bool；当前请求是否允许直接输出答案片段。
def answer_stream_active() -> bool:
    return _ANSWER_STREAM.get() is not None


# 方法说明：emit_answer_chunk
# 作用：向本次请求的答案流回调发送一个文本片段。
# 入参：
#   chunk（str）：当前文档文本片段。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
async def emit_answer_chunk(chunk: str) -> None:
    queue = _ANSWER_STREAM.get()
    if queue is not None and chunk:
        await queue.put(chunk)


# 方法说明：use_answer_stream
# 作用：绑定本次请求的答案流回调，并在结束后恢复原上下文。
# 入参：
#   queue（asyncio.Queue[str | WorkflowProgress]）：文档任务队列。
# 出参：Iterator[None]；None（未取得结果）的迭代器。
@contextmanager
def use_answer_stream(queue: asyncio.Queue[str | WorkflowProgress]) -> Iterator[None]:
    token = _ANSWER_STREAM.set(queue)
    try:
        yield
    finally:
        _ANSWER_STREAM.reset(token)


# 方法说明：suppress_answer_stream
# 作用：临时关闭原始答案流输出，等待安全审核完成后发布。
# 入参：
#   无显式入参。
# 出参：Iterator[None]；None（未取得结果）的迭代器。
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


# 方法说明：use_progress_stream
# 作用：绑定 Workflow 进度回调，供节点发布阶段事件。
# 入参：
#   queue（asyncio.Queue）：文档任务队列。
# 出参：Iterator[None]；None（未取得结果）的迭代器。
@contextmanager
def use_progress_stream(queue: asyncio.Queue) -> Iterator[None]:
    token = _PROGRESS_STREAM.set(queue)
    try:
        yield
    finally:
        _PROGRESS_STREAM.reset(token)


# 方法说明：emit_workflow_progress
# 作用：向本次请求发送 Workflow 阶段进度事件。
# 入参：
#   stage（str）：当前执行或模型调用阶段。
#   message（str）：本轮用户消息或问题文本。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
async def emit_workflow_progress(stage: str, message: str) -> None:
    queue = _PROGRESS_STREAM.get()
    if queue is not None:
        await queue.put(WorkflowProgress(stage=stage, message=message))
