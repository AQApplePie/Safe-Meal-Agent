"""Agent 调用端口。

应用层中有多个用例需要“执行一次 Agent 请求”：

- ChatTurnService：真实用户聊天，需要会话持久化和长期记忆；
- InternalAgentProcessService：受信任内部服务调用，可按权限请求Trace。

这些用例不应该直接依赖 ``AgentGraphRunnerService`` 具体类，因此把最小能力抽成
Protocol。未来如果 Agent Orchestrator 本身也改成远程 client，只要实现该协议，
上层用例无需改流程。
"""

from __future__ import annotations

from typing import Protocol

from safemeal.application.contracts.agent import AgentProcessResponse
from safemeal.shared.contracts.agent_context import AgentContext


class AgentProcessor(Protocol):
    """应用用例依赖的最小 Agent 执行能力。"""

    async def process(
        self,
        message: str,
        session_id: str,
        *,
        context: AgentContext | None = None,
        include_trace: bool = False,
    ) -> AgentProcessResponse:
        """执行一次 Agent 请求并返回结构化响应。"""
        ...
