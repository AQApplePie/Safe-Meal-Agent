"""内部 Agent 请求处理用例服务。

该服务服务于 ``/api/v1/agent/process`` 这类服务间接口。它只负责内部请求的
应用编排：

- 根据请求决定是否加载用户长期记忆；
- 调用 AgentProcessor 执行 Agent 图；
- 返回稳定的 AgentProcessResponse。

HTTP Router 不再直接知道 Memory 和 Agent 的串联顺序。
"""

from __future__ import annotations

import asyncio

from SafeMealAgent.back.application.ports import AgentProcessor
from SafeMealAgent.back.shared.contracts.agent import (
    AgentProcessRequest,
    AgentProcessResponse,
)
from SafeMealAgent.back.shared.contracts.agent_context import AgentContext
from SafeMealAgent.back.shared.contracts.memory import AgentMemoryProvider
from SafeMealAgent.back.shared.types import to_json_object_list
from .conversation_memory import ConversationMemoryManager, MemoryRelevanceSelector


class InternalAgentProcessService:
    """编排一次内部 Agent 调用的应用服务。

    Args:
        agent_processor: Agent 执行端口，当前实现通常是 AgentGraphRunnerService。
        memory_provider: 长期记忆读取端口，当前默认通过 HTTP 调 Memory Service。
    """

    def __init__(
        self,
        *,
        agent_processor: AgentProcessor,
        memory_provider: AgentMemoryProvider,
        conversation_manager: ConversationMemoryManager | None = None,
        memory_selector: MemoryRelevanceSelector | None = None,
    ) -> None:
        self._agent_processor = agent_processor
        self._memory_provider = memory_provider
        self._conversation_manager = conversation_manager
        self._memory_selector = memory_selector or MemoryRelevanceSelector()

    async def handle(self, request: AgentProcessRequest) -> AgentProcessResponse:
        """处理服务间 Agent 请求。

        Args:
            request: 受信任内部服务提交的Agent请求。

        Returns:
            Agent 执行后的结构化响应；可包含完整 Trace。
        """

        # HTTP callers may provide conversation history, but privileged context slices
        # (observations, memories and profiles) must only come from server-side providers.
        # Treating caller-supplied observations as trusted evidence would let a client forge
        # database results or persist prompt-injection instructions as memory.
        supplied_history = (
            request.context.conversation_history
            if request.context is not None
            else request.history
        )
        prepared = (
            self._conversation_manager.prepare(
                supplied_history,
                current_message=request.message,
            )
            if self._conversation_manager is not None
            else None
        )
        context = AgentContext(
            conversation_history=(
                prepared.history if prepared is not None else supplied_history
            ),
            episodic_memories=(
                prepared.episodic_memories if prepared is not None else []
            ),
            context_metadata={
                "user_id": request.user_id,
                "session_id": request.session_id,
                "source": "internal_agent_process",
                "estimated_context_tokens": (
                    prepared.estimated_tokens if prepared is not None else None
                ),
            },
        )

        if request.use_user_memory and not context.user_memories:
            # Memory provider 可能是同步 HTTP client，也可能是本地服务；
            # 放入线程，避免阻塞 FastAPI 事件循环。
            user_memories = await asyncio.to_thread(
                self._memory_provider.load_agent_memories,
                user_id=request.user_id,
                limit=100,
            )
            context.user_memories = self._memory_selector.select(
                request.message,
                to_json_object_list(user_memories),
            )

        result = await self._agent_processor.process(
            request.message,
            request.session_id,
            context=context,
            include_trace=request.include_trace,
        )

        # 正常实现会直接返回 AgentProcessResponse；这里保留一次校验转换，
        # 方便测试替身或未来远程 client 返回 dict 时仍保持契约稳定。
        response = (
            result
            if isinstance(result, AgentProcessResponse)
            else AgentProcessResponse.model_validate(result)
        )
        return response
