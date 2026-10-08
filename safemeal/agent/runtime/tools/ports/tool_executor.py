"""Tool execution boundary used by the Agent graph.

具体工具、参数校验和数据库访问由基础设施层实现。application 层只声明 Agent 图
需要什么能力，避免把本地工具运行时或外部系统适配器引入核心编排逻辑。
"""

from typing import Protocol

from safemeal.agent.runtime.tools.contracts.base import ToolResult, ToolSpecification

from safemeal.agent.contracts.decisions import ToolCall


class ToolExecutor(Protocol):

    def specifications(self) -> list[ToolSpecification]:
        """返回 Planner 可见的工具说明。"""

    async def invoke(self, call: ToolCall) -> ToolResult:
        """执行一次工具调用。"""

    async def invoke_many(self, calls: list[ToolCall]) -> list[ToolResult]:
        """并发执行多次工具调用。"""


__all__ = ["ToolExecutor"]
