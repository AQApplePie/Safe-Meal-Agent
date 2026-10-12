"""定义应用层依赖的能力端口。"""

from typing import Protocol
from safemeal.agent.contracts.api import (
    AgentProcessResponse,
    AgentResumeResult,
)
from safemeal.agent.contracts.context import AgentContext


# 类说明（接口类）：AgentInvoker
# 作用：定义Agent 调用接口的能力契约，供应用层与具体实现解耦。
class AgentInvoker(Protocol):
    # 方法说明：process
    # 作用：执行Agent 调用接口的请求处理，组装本轮结果。
    # 入参：
    #   message（str）：本轮用户消息或问题文本。
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   context（AgentContext | None）：本轮执行上下文；默认值为 None。
    # 出参：AgentProcessResponse；Agent 内部处理响应。
    async def process(
        self,
        message: str,
        session_id: str,
        *,
        context: AgentContext | None = None,
    ) -> AgentProcessResponse: ...


# 类说明（接口类）：ResumableAgent
# 作用：定义支持人工审批恢复的 Agent 接口的能力契约，供应用层与具体实现解耦。
class ResumableAgent(AgentInvoker, Protocol):
    # 方法说明：resume
    # 作用：从持久化中断状态恢复当前审批任务并整理执行结果。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   approved（bool）：用户是否明确同意执行当前待审批操作。
    # 出参：'AgentResumeResult'；Agent 审批恢复结果。
    async def resume(
        self, session_id: str, *, approved: bool
    ) -> "AgentResumeResult": ...
