"""校验并在超时和并发限制内执行本地工具。"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from safemeal.agent.contracts.decisions import ToolCall
from safemeal.agent.runtime.tools.contracts.base import ToolResult, ToolSpecification
from safemeal.agent.runtime.tools.ports.handler import ToolHandler
from safemeal.shared.types import JsonObject


class LocalToolExecutor:

    def __init__(
        self,
        tools: Iterable[ToolHandler[Any]],
        timeout_seconds: float = 60.0,
        max_concurrency: int = 8,
    ) -> None:

        tool_list = list(tools)
        names = [tool.name for tool in tool_list]
        duplicate_names = sorted({name for name in names if names.count(name) > 1})
        if duplicate_names:
            raise ValueError(f"重复的 Tool 名称：{duplicate_names}")
        self._tools = {tool.name: tool for tool in tool_list}
        self._timeout_seconds = timeout_seconds
        self._concurrency = asyncio.Semaphore(max(1, max_concurrency))

    def specifications(self) -> list[ToolSpecification]:

        return [tool.specification() for tool in self._tools.values()]

    async def _invoke_handler(
        self,
        tool_name: str,
        call_id: str,
        arguments: JsonObject,
    ) -> ToolResult:

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

    async def invoke(self, call: ToolCall) -> ToolResult:

        return await self._invoke_handler(call.tool_name, call.id, call.arguments)

    async def invoke_many(self, calls: list[ToolCall]) -> list[ToolResult]:

        if not calls:
            return []
        return list(await asyncio.gather(*(self.invoke(call) for call in calls)))


__all__ = ["LocalToolExecutor"]
