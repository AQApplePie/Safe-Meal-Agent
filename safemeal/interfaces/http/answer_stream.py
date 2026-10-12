"""实现 HTTP 接口层的请求与响应适配。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
import json
from typing import Any, Protocol, TypeVar

from safemeal.agent.workflow.streaming import use_answer_stream
from safemeal.shared.types import JsonObject
from safemeal.agent.contracts.workflow.stream import WorkflowProgress
from safemeal.agent.workflow.streaming import use_progress_stream


# 类说明（接口类）：AnswerMessage
# 作用：定义助手答案消息的能力契约，供应用层与具体实现解耦。
class AnswerMessage(Protocol):
    # 字段说明：message
    # 作用：本轮用户消息或问题文本。
    # 类型：str。
    message: str


ResponseT = TypeVar("ResponseT", bound=AnswerMessage)


# 方法说明：_event
# 作用：将事件名称和 JSON 载荷编码为 SSE 协议文本。
# 入参：
#   name（str）：当前对象或字段的名称。
#   payload（JsonObject）：当前协议或持久化操作的数据载荷。
# 出参：str；符合 SSE 协议的事件文本。
def _event(name: str, payload: JsonObject) -> str:
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


# 方法说明：stream_answer_events
# 作用：将答案片段、阶段信息与结束状态编码为流事件。
# 入参：
#   operation_factory（Callable[[], Coroutine[Any, Any,
# ResponseT]]）：为每次事务尝试创建业务操作的工厂。
#   completed_payload（Callable[[ResponseT, bool], JsonObject]）：已完成轮次保存的响应载荷。
#   timeout_seconds（float）：操作超时上限，单位秒。
#   chunk_chars（int）：文档分块的目标字符数。
# 出参：AsyncIterator[str]；可逐条发送的 SSE 事件异步迭代器。
async def stream_answer_events(
    operation_factory: Callable[[], Coroutine[Any, Any, ResponseT]],
    *,
    completed_payload: Callable[[ResponseT, bool], JsonObject],
    timeout_seconds: float,
    chunk_chars: int,
) -> AsyncIterator[str]:

    queue: asyncio.Queue[str | WorkflowProgress] = asyncio.Queue()
    with use_answer_stream(queue), use_progress_stream(queue):
        task: asyncio.Task[ResponseT] = asyncio.create_task(operation_factory())

    yield _event("accepted", {})
    degraded = False
    streamed = False
    pending_chunk = asyncio.create_task(queue.get())

    done, _ = await asyncio.wait(
        {task, pending_chunk},
        timeout=timeout_seconds,
        return_when=asyncio.FIRST_COMPLETED,
    )
    if not done:
        degraded = True
        yield _event(
            "degraded",
            {"reason": "first_answer_timeout", "fallback": "continued"},
        )

    while not task.done():
        if pending_chunk in done:
            chunk = pending_chunk.result()
            if isinstance(chunk, WorkflowProgress):
                yield _event(
                    "progress", {"stage": chunk.stage, "message": chunk.message}
                )
            else:
                streamed = True
                yield _event("answer", {"delta": chunk})
            pending_chunk = asyncio.create_task(queue.get())
        done, _ = await asyncio.wait(
            {task, pending_chunk}, return_when=asyncio.FIRST_COMPLETED
        )

    if pending_chunk.done() and not pending_chunk.cancelled():
        chunk = pending_chunk.result()
        if isinstance(chunk, WorkflowProgress):
            yield _event("progress", {"stage": chunk.stage, "message": chunk.message})
        else:
            streamed = True
            yield _event("answer", {"delta": chunk})
    else:
        pending_chunk.cancel()
        await asyncio.gather(pending_chunk, return_exceptions=True)

    while not queue.empty():
        chunk = queue.get_nowait()
        if isinstance(chunk, WorkflowProgress):
            yield _event("progress", {"stage": chunk.stage, "message": chunk.message})
        else:
            streamed = True
            yield _event("answer", {"delta": chunk})

    try:
        result = task.result()
    except Exception as exc:
        error_code = str(
            getattr(exc, "error_code", None)
            or getattr(exc, "code", None)
            or "stream_failed"
        )
        yield _event(
            "error",
            {
                "message": "Answer stream failed",
                "error_code": error_code,
                "partial_answer": streamed,
            },
        )
        yield _event("done", {"status": "error", "degraded": True})
        return

    if not streamed:
        for index in range(0, len(result.message), chunk_chars):
            yield _event(
                "answer", {"delta": result.message[index : index + chunk_chars]}
            )

    yield _event("done", completed_payload(result, degraded))


__all__ = ["stream_answer_events"]
