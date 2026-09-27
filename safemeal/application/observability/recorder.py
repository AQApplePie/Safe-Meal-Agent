"""基于 ContextVar 的 Agent Trace 采集器。"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
from typing import Iterator, Literal, Mapping, Optional
from datetime import datetime

from loguru import logger

from safemeal.application.contracts.observability.trace import (
    AgentRunTrace,
    ModelCallTrace,
    SpanTrace,
    TokenUsage,
    ToolCallTrace,
    utc_now,
)
from .payload import safe_trace_payload
from safemeal.shared.types import JsonObject, to_json_object
from .cost import CostUsage, ModelPrice, estimate_trace_cost


class AgentTraceRecorder:
    """对一个 AgentRunTrace 进行追加和收尾。"""

    def __init__(
        self,
        question: str,
        session_id: str,
        *,
        model_pricing: Mapping[str, ModelPrice] | None = None,
        cost_currency: str = "CNY",
        **metadata: object,
    ) -> None:
        """创建请求级 Recorder。

        Args:
            question: 当前用户问题。
            session_id: 业务会话 ID。
            metadata: 模型、版本等运行标签。
        """

        self.trace = AgentRunTrace(
            question=question,
            session_id=session_id,
            metadata=safe_trace_payload(metadata),
        )
        self._model_pricing = dict(model_pricing or {})
        self._cost_currency = cost_currency
        self._started_perf = perf_counter()

    def cost_usage(self) -> CostUsage:
        """Estimate the current run cost with composition-root configuration."""

        return estimate_trace_cost(
            self.trace,
            self._model_pricing,
            currency=self._cost_currency,
        )

    def finish(
        self,
        *,
        status: Literal["ok", "error"],
        iterations: int = 0,
        final_answer: str = "",
        sources: Optional[list[JsonObject]] = None,
        error: Optional[str] = None,
    ) -> None:
        """结束请求级 Trace。

        Args:
            status: 请求最终状态。
            iterations: 工具执行轮次。
            final_answer: 最终答案。
            sources: 最终返回来源。
            error: 请求级错误。
        """

        self.trace.finished_at = utc_now()
        self.trace.total_latency_ms = round(
            (perf_counter() - self._started_perf) * 1000,
            3,
        )
        self.trace.status = status
        self.trace.iterations = iterations
        self.trace.final_answer = final_answer
        self.trace.sources = [to_json_object(source) for source in (sources or [])]
        self.trace.error = error

    def append_tool_call(self, item: ToolCallTrace) -> None:
        """追加工具调用记录。"""

        self.trace.tool_calls.append(item)

    def append_model_call(self, item: ModelCallTrace) -> None:
        """追加模型调用记录。"""

        self.trace.model_calls.append(item)


_CURRENT_TRACE: ContextVar[Optional[AgentTraceRecorder]] = ContextVar(
    "safemeal_current_agent_trace",
    default=None,
)


def current_trace() -> Optional[AgentTraceRecorder]:
    """返回当前异步上下文中的请求级 Recorder。"""

    return _CURRENT_TRACE.get()


@contextmanager
def use_trace(recorder: AgentTraceRecorder) -> Iterator[AgentTraceRecorder]:
    """在当前异步上下文中启用 Recorder。

    Args:
        recorder: 请求级 Trace Recorder。
    """

    token = _CURRENT_TRACE.set(recorder)
    try:
        yield recorder
    finally:
        _CURRENT_TRACE.reset(token)


class SpanHandle:
    """允许调用方在异步操作后补充 Span 输出的句柄。"""

    def __init__(self, span: Optional[SpanTrace]) -> None:
        """创建句柄。

        Args:
            span: 活动 Span；没有 Recorder 时为空。
        """

        self.span = span
        self._started_perf = perf_counter()

    def set_output(self, value: object) -> None:
        """记录尺寸受控的阶段输出。"""

        if self.span is not None:
            self.span.output = safe_trace_payload(value)

    def set_error(self, error: BaseException | str) -> None:
        """记录阶段错误并把状态标记为 error。"""

        if self.span is not None:
            self.span.error = str(error)
            self.span.status = "error"

    def finish(self) -> None:
        """结束 Span 并计算耗时。"""

        if self.span is None:
            return
        self.span.finished_at = utc_now()
        self.span.duration_ms = round(
            (perf_counter() - self._started_perf) * 1000,
            3,
        )
        if self.span.status == "running":
            self.span.status = "ok"


@contextmanager
def trace_span(
    kind: str,
    name: str,
    input_data: object = None,
) -> Iterator[SpanHandle]:
    """记录 Agent 节点或内部阶段。

    Args:
        kind: Span 类型。
        name: 节点或阶段名称。
        input_data: 尺寸受控后写入的阶段输入。
    """

    recorder = current_trace()
    span = None
    run_id = recorder.trace.run_id if recorder is not None else "-"
    session_id = recorder.trace.session_id if recorder is not None else "-"
    logger.info(
        "agent.span.start run_id={} session_id={} kind={} name={}",
        run_id,
        session_id,
        kind,
        name,
    )
    if recorder is not None:
        span = SpanTrace(
            kind=kind,
            name=name,
            input=safe_trace_payload(input_data),
        )
        recorder.trace.spans.append(span)
    handle = SpanHandle(span)
    try:
        yield handle
    except Exception as exc:
        handle.set_error(exc)
        logger.exception(
            "agent.span.failed run_id={} session_id={} kind={} name={} "
            "elapsed_ms={:.3f} error={}",
            run_id,
            session_id,
            kind,
            name,
            (perf_counter() - handle._started_perf) * 1000,
            exc,
        )
        raise
    finally:
        handle.finish()
        logger.info(
            "agent.span.completed run_id={} session_id={} kind={} name={} "
            "status={} elapsed_ms={:.3f}",
            run_id,
            session_id,
            kind,
            name,
            span.status if span is not None else "untraced",
            (perf_counter() - handle._started_perf) * 1000,
        )


def extract_token_usage(response: object) -> tuple[TokenUsage, bool]:
    """从 LangChain AIMessage 中提取供应商 Token usage。

    Args:
        response: 原始模型响应对象。
    """

    if response is None:
        return TokenUsage(), False

    usage_payload = getattr(response, "usage_metadata", None)
    usage = usage_payload if isinstance(usage_payload, dict) else {}
    response_metadata_payload = getattr(response, "response_metadata", None)
    response_metadata = (
        response_metadata_payload if isinstance(response_metadata_payload, dict) else {}
    )
    token_usage_payload = (
        response_metadata.get("token_usage") or response_metadata.get("usage") or {}
    )
    token_usage = token_usage_payload if isinstance(token_usage_payload, dict) else {}
    input_tokens = int(
        usage.get("input_tokens")
        or token_usage.get("prompt_tokens")
        or token_usage.get("input_tokens")
        or 0
    )
    output_tokens = int(
        usage.get("output_tokens")
        or token_usage.get("completion_tokens")
        or token_usage.get("output_tokens")
        or 0
    )
    total_tokens = int(
        usage.get("total_tokens")
        or token_usage.get("total_tokens")
        or input_tokens + output_tokens
    )
    input_details = usage.get("input_token_details") or {}
    cached_tokens = int(
        input_details.get("cache_read") or token_usage.get("cached_tokens") or 0
    )
    return (
        TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_tokens=cached_tokens,
        ),
        bool(usage or token_usage),
    )


def record_model_call(
    *,
    stage: str,
    model: str,
    temperature: float,
    messages: object,
    response: object,
    parsed_response: object,
    started_at: datetime,
    started_perf: float,
    error: Optional[str] = None,
) -> None:
    """把一次已完成的模型调用写入当前 Trace。

    Args:
        stage: Planner、Reflection 或 Responder。
        model: 模型名称。
        temperature: 调用温度。
        messages: 模型输入消息。
        response: 原始模型响应。
        parsed_response: 业务层使用的解析后响应。
        started_at: 调用开始时间。
        started_perf: ``perf_counter`` 开始值。
        error: 可选错误信息。
    """

    usage, usage_available = extract_token_usage(response)
    elapsed_ms = round((perf_counter() - started_perf) * 1000, 3)
    status = "error" if error else "ok"
    recorder = current_trace()
    run_id = recorder.trace.run_id if recorder is not None else "-"
    session_id = recorder.trace.session_id if recorder is not None else "-"
    logger.info(
        "agent.model.completed run_id={} session_id={} stage={} model={} "
        "status={} elapsed_ms={} input_tokens={} output_tokens={} "
        "usage_available={} error={}",
        run_id,
        session_id,
        stage,
        model,
        status,
        elapsed_ms,
        usage.input_tokens,
        usage.output_tokens,
        usage_available,
        error,
    )
    if recorder is None:
        return

    message_metadata = []
    if isinstance(messages, (list, tuple)):
        for message in messages:
            if isinstance(message, (list, tuple)) and len(message) >= 2:
                message_metadata.append(
                    {"role": str(message[0]), "content_chars": len(str(message[1]))}
                )
            elif isinstance(message, dict):
                message_metadata.append(
                    {
                        "role": str(message.get("role", "unknown")),
                        "content_chars": len(str(message.get("content", ""))),
                    }
                )
    if isinstance(parsed_response, str):
        response_metadata: object = {
            "type": "text",
            "content_chars": len(parsed_response),
        }
    elif hasattr(parsed_response, "model_dump"):
        parsed_payload = parsed_response.model_dump()
        response_metadata = {
            "type": type(parsed_response).__name__,
            "fields": sorted(parsed_payload),
            "decision": parsed_payload.get("decision"),
        }
    else:
        response_metadata = {"type": type(parsed_response).__name__}

    recorder.append_model_call(
        ModelCallTrace(
            stage=stage,
            model=model,
            temperature=temperature,
            started_at=started_at,
            finished_at=utc_now(),
            latency_ms=elapsed_ms,
            messages=safe_trace_payload(message_metadata),
            response=safe_trace_payload(response_metadata),
            usage=usage,
            usage_available=usage_available,
            error=error,
        )
    )


def trace_json(
    trace: AgentRunTrace,
    *,
    model_pricing: Mapping[str, ModelPrice] | None = None,
    cost_currency: str = "CNY",
) -> JsonObject:
    """把 Trace 转换为报告可保存的 JSON 字典。

    Args:
        trace: 已结束或进行中的 AgentRunTrace。
    """

    payload = trace.model_dump(mode="json")
    payload["token_usage"] = trace.token_usage.model_dump()
    payload["token_usage_complete"] = bool(trace.model_calls) and all(
        item.usage_available for item in trace.model_calls
    )
    cost = estimate_trace_cost(
        trace,
        model_pricing or {},
        currency=cost_currency,
    )
    payload["cost_usage"] = {
        "currency": cost.currency,
        "input_cost": cost.input_cost,
        "output_cost": cost.output_cost,
        "cached_input_cost": cost.cached_input_cost,
        "total_cost": cost.total_cost,
        "priced_calls": cost.priced_calls,
        "total_calls": cost.total_calls,
    }
    payload["cost_usage_complete"] = cost.complete
    return to_json_object(payload)
