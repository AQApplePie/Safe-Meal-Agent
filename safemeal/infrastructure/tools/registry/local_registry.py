"""本地工具注册表适配器。

Agent 主流程默认使用本地工具，避免每轮工具调用都多一次 HTTP 跳转。
本适配器把本地 Tool runtime 包装成 Agent 图需要的
``specifications / invoke / invoke_many`` 接口，同时保留 Tool Trace 记录。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from time import perf_counter
from typing import List

from loguru import logger

from safemeal.application.agents.models import ToolCall
from safemeal.application.observability import (
    ToolCallTrace,
    current_trace,
    safe_trace_payload,
)
from safemeal.infrastructure.tools.registry.runtime import ToolRuntimeRegistry
from safemeal.shared.contracts.tools import ToolResult, ToolSpecification


class LocalToolRegistry:
    """把本地 Tool runtime 适配成 Agent 图可用的工具注册表。"""

    def __init__(self, runtime_registry: ToolRuntimeRegistry) -> None:
        """初始化本地工具注册表。

        Args:
            runtime_registry: 本地工具运行时注册表。
        """

        self._runtime_registry = runtime_registry

    def specifications(self) -> List[ToolSpecification]:
        """返回 Planner 可见的工具说明。"""

        return self._runtime_registry.specifications()

    async def invoke(self, call: ToolCall) -> ToolResult:
        """执行一个本地工具调用，并记录工具级 Trace。"""

        started_at = datetime.now(timezone.utc)
        started_perf = perf_counter()
        recorder = current_trace()
        run_id = recorder.trace.run_id if recorder is not None else "-"
        session_id = recorder.trace.session_id if recorder is not None else "-"
        logger.info(
            "agent.local_tool.start run_id={} session_id={} call_id={} tool={}",
            run_id,
            session_id,
            call.id,
            call.tool_name,
        )

        validation_error = None
        arguments_valid = True
        response = await self._runtime_registry.invoke(
            call.tool_name,
            call.id,
            call.arguments,
        )
        result = response
        if result.error and result.error.startswith("工具参数校验失败"):
            arguments_valid = False
            validation_error = result.error

        elapsed_ms = round((perf_counter() - started_perf) * 1000, 3)
        logger.info(
            "agent.local_tool.completed run_id={} session_id={} call_id={} tool={} "
            "arguments_valid={} status={} elapsed_ms={} error={}",
            run_id,
            session_id,
            call.id,
            call.tool_name,
            arguments_valid,
            "ok" if result.ok else "error",
            elapsed_ms,
            result.error,
        )
        if recorder is not None:
            recorder.append_tool_call(
                ToolCallTrace(
                    call_id=call.id,
                    tool_name=call.tool_name,
                    started_at=started_at,
                    finished_at=datetime.now(timezone.utc),
                    latency_ms=elapsed_ms,
                    arguments=safe_trace_payload(call.arguments),
                    arguments_valid=arguments_valid,
                    validation_error=validation_error,
                    ok=result.ok,
                    status=result.status,
                    result=safe_trace_payload(result.data),
                    error=result.error,
                    error_code=result.error_code,
                    retryable=result.retryable,
                )
            )
        return result

    async def invoke_many(self, calls: List[ToolCall]) -> List[ToolResult]:
        """并发执行多个本地工具调用。"""

        if not calls:
            return []
        return list(await asyncio.gather(*(self.invoke(call) for call in calls)))


__all__ = ["LocalToolRegistry"]
