"""校验并在超时和并发限制内执行本地工具。"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from safemeal.agent.contracts.decisions import ToolCall
from safemeal.agent.runtime.tools.contracts.base import ToolResult, ToolSpecification
from safemeal.agent.runtime.tools.ports.handler import ToolHandler
from safemeal.shared.types import JsonObject


# 类说明（业务或基础设施实现类）：LocalToolExecutor
# 作用：实现本地工具注册与执行器，封装该组件的业务处理与依赖协作。
class LocalToolExecutor:
    # 方法说明：__init__
    # 作用：初始化本地工具注册与执行器，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   tools（Iterable[ToolHandler[Any]]）：本轮可用工具集合。
    #   timeout_seconds（float）：操作超时上限，单位秒；默认值为 60.0。
    #   max_concurrency（int）：同时执行的最大任务数；默认值为 8。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
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
        # 实例属性说明：_tools
        # 作用：本轮可用工具集合。
        self._tools = {tool.name: tool for tool in tool_list}
        # 实例属性说明：_timeout_seconds
        # 作用：操作超时上限，单位秒。
        self._timeout_seconds = timeout_seconds
        # 实例属性说明：_concurrency
        # 作用：控制同时执行任务或工具数量的异步信号量。
        self._concurrency = asyncio.Semaphore(max(1, max_concurrency))

    # 方法说明：specifications
    # 作用：汇总全部已注册工具的规范，供 Agent 规划使用。
    # 入参：
    #   无显式入参。
    # 出参：list[ToolSpecification]；工具用途与参数规范的集合。
    def specifications(self) -> list[ToolSpecification]:

        return [tool.specification() for tool in self._tools.values()]

    # 方法说明：_invoke_handler
    # 作用：调用单个工具处理器并将异常转换为标准工具结果。
    # 入参：
    #   tool_name（str）：工具名称。
    #   call_id（str）：工具调用标识。
    #   arguments（JsonObject）：按工具 Schema 校验后的调用参数。
    # 出参：ToolResult；标准工具执行结果。
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
            # 方法说明：invoke_with_capacity
            # 作用：在资源容量限制内执行图调用，避免无限并发。
            # 入参：
            #   无显式入参。
            # 出参：ToolResult；标准工具执行结果。
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

    # 方法说明：invoke
    # 作用：调用本地工具注册与执行器的执行入口并返回业务结果。
    # 入参：
    #   call（ToolCall）：单个结构化工具调用。
    # 出参：ToolResult；标准工具执行结果。
    async def invoke(self, call: ToolCall) -> ToolResult:

        return await self._invoke_handler(call.tool_name, call.id, call.arguments)

    # 方法说明：invoke_many
    # 作用：按并发上限执行多个工具调用并保持结果对应关系。
    # 入参：
    #   calls（list[ToolCall]）：待执行或待审核的工具调用列表。
    # 出参：list[ToolResult]；标准工具执行结果的集合。
    async def invoke_many(self, calls: list[ToolCall]) -> list[ToolResult]:

        if not calls:
            return []
        return list(await asyncio.gather(*(self.invoke(call) for call in calls)))


__all__ = ["LocalToolExecutor"]
