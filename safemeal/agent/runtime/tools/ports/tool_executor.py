"""Tool execution boundary used by the Agent graph.

具体工具、参数校验和数据库访问由基础设施层实现。application 层只声明 Agent 图
需要什么能力，避免把本地工具运行时或外部系统适配器引入核心编排逻辑。
"""

from typing import Protocol

from safemeal.agent.runtime.tools.contracts.base import ToolResult, ToolSpecification

from safemeal.agent.contracts.decisions import ToolCall


# 类说明（接口类）：ToolExecutor
# 作用：定义工具执行能力接口的能力契约，供应用层与具体实现解耦。
class ToolExecutor(Protocol):
    # 方法说明：specifications
    # 作用：返回 Planner 可见的工具说明。
    # 入参：
    #   无显式入参。
    # 出参：list[ToolSpecification]；工具用途与参数规范的集合。
    def specifications(self) -> list[ToolSpecification]:
        """返回 Planner 可见的工具说明。"""

    # 方法说明：invoke
    # 作用：执行一次工具调用。
    # 入参：
    #   call（ToolCall）：单个结构化工具调用。
    # 出参：ToolResult；标准工具执行结果。
    async def invoke(self, call: ToolCall) -> ToolResult:
        """执行一次工具调用。"""

    # 方法说明：invoke_many
    # 作用：并发执行多次工具调用。
    # 入参：
    #   calls（list[ToolCall]）：待执行或待审核的工具调用列表。
    # 出参：list[ToolResult]；标准工具执行结果的集合。
    async def invoke_many(self, calls: list[ToolCall]) -> list[ToolResult]:
        """并发执行多次工具调用。"""


__all__ = ["ToolExecutor"]
