"""本地工具运行时。

本模块负责工具说明、参数校验、超时控制和工具实现调度。
它不依赖 Agent 图内部状态，可由应用层稳定调用和独立测试。
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError
from loguru import logger

from SafeMealAgent.back.application.errors import ApplicationError, DatabaseOperationError
from SafeMealAgent.back.shared.contracts.tools import ToolResult, ToolSpecification
from SafeMealAgent.back.shared.types import JsonObject, JsonValue, to_json_object, to_json_value
from SafeMealAgent.back.infrastructure.operations.rate_limit import RedisTokenBucket
from SafeMealAgent.back.application.observability.metrics import RATE_LIMIT_DECISIONS


ToolArgs = TypeVar("ToolArgs", bound=BaseModel)


class ToolHandler(Generic[ToolArgs], ABC):
    """本地具体工具的基础抽象。

    具体工具只需要声明名称、描述、参数模型，并实现 ``run``。运行时统一负责：

    - 生成 ToolSpecification；
    - 使用 Pydantic 校验参数；
    - 把返回值转换为 JSON 友好的 ToolResult。
    """

    name: str
    description: str
    args_schema: type[ToolArgs]

    def specification(self) -> ToolSpecification:
        """返回给 Planner 或调用方读取的工具说明。"""

        return ToolSpecification(
            name=self.name,
            description=self.description,
            arguments_schema=to_json_object(self.args_schema.model_json_schema()),
        )

    async def invoke(self, call_id: str, arguments: JsonObject) -> ToolResult:
        """校验参数并执行工具。"""

        try:
            parsed = self.args_schema.model_validate(arguments)
        except ValidationError as exc:
            return ToolResult(
                call_id=call_id,
                tool_name=self.name,
                ok=False,
                status="rejected",
                error=f"工具参数校验失败：{exc}",
                error_code="invalid_tool_arguments",
            )

        try:
            data = to_json_value(await self.run(parsed))
            return ToolResult(
                call_id=call_id,
                tool_name=self.name,
                ok=True,
                data=data,
            )
        except Exception as exc:
            logger.warning(
                "tool.handler.failed tool={} error_type={}",
                self.name,
                type(exc).__name__,
            )
            error_code = (
                exc.code
                if isinstance(exc, ApplicationError)
                else "tool_execution_failed"
            )
            retryable = exc.retryable if isinstance(exc, ApplicationError) else False
            return ToolResult(
                call_id=call_id,
                tool_name=self.name,
                ok=False,
                status=(
                    "unavailable"
                    if isinstance(exc, DatabaseOperationError)
                    else "error"
                ),
                error=str(exc),
                error_code=error_code,
                retryable=retryable,
            )

    @abstractmethod
    async def run(self, arguments: ToolArgs) -> JsonValue | BaseModel:
        """执行工具的确定性逻辑。"""


class ToolRuntimeRegistry:
    """本地工具注册表。"""

    def __init__(
        self,
        tools: Iterable[ToolHandler[Any]],
        timeout_seconds: float = 60.0,
        max_concurrency: int = 8,
        distributed_limiter: RedisTokenBucket | None = None,
        rate_limit_per_minute: int = 600,
    ) -> None:
        tool_list = list(tools)
        names = [tool.name for tool in tool_list]
        duplicate_names = sorted({name for name in names if names.count(name) > 1})
        if duplicate_names:
            raise ValueError(f"重复的 Tool 名称：{duplicate_names}")
        self._tools = {tool.name: tool for tool in tool_list}
        self._timeout_seconds = timeout_seconds
        self._concurrency = asyncio.Semaphore(max(1, max_concurrency))
        self._distributed_limiter = distributed_limiter
        self._rate_limit_per_minute = rate_limit_per_minute

    def specifications(self) -> list[ToolSpecification]:
        """列出当前可用工具说明。"""

        return [tool.specification() for tool in self._tools.values()]

    async def invoke(
        self,
        tool_name: str,
        call_id: str,
        arguments: JsonObject,
    ) -> ToolResult:
        """按工具名称执行一次本地Tool请求。"""

        tool = self._tools.get(tool_name)
        if tool is None:
            return ToolResult(
                call_id=call_id,
                tool_name=tool_name,
                ok=False,
                status="rejected",
                error=f"未知工具：{tool_name}",
                error_code="unknown_tool",
            )

        try:

            async def invoke_with_capacity() -> ToolResult:
                if self._distributed_limiter is not None:
                    decision = await self._distributed_limiter.acquire(
                        tool_name,
                        capacity=self._rate_limit_per_minute,
                        refill_per_second=self._rate_limit_per_minute / 60,
                    )
                    if not decision.allowed:
                        RATE_LIMIT_DECISIONS.labels(
                            layer="tool", outcome="rejected"
                        ).inc()
                        return ToolResult(
                            call_id=call_id,
                            tool_name=tool_name,
                            ok=False,
                            status="unavailable",
                            error=f"工具分布式限流，{decision.retry_after_ms}ms 后重试",
                            error_code="tool_rate_limited",
                            retryable=True,
                        )
                    RATE_LIMIT_DECISIONS.labels(layer="tool", outcome="allowed").inc()
                async with self._concurrency:
                    return await tool.invoke(call_id, arguments)

            return await asyncio.wait_for(
                invoke_with_capacity(),
                timeout=self._timeout_seconds,
            )
        except asyncio.TimeoutError:
            return ToolResult(
                call_id=call_id,
                tool_name=tool_name,
                ok=False,
                status="timeout",
                error=f"工具执行超过 {self._timeout_seconds:g} 秒",
                error_code="tool_timeout",
                retryable=True,
            )

    async def close(self) -> None:
        if self._distributed_limiter is not None:
            await self._distributed_limiter.close()


__all__ = [
    "ToolHandler",
    "ToolRuntimeRegistry",
]
