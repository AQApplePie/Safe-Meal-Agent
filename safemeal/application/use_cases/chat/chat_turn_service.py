"""Chat Turn 应用用例服务。

本模块负责完成“一轮真实聊天”的应用级编排：

1. 创建或复用会话，并保存用户问题；
2. 构建 AgentContext；
3. 调用 Agent Orchestrator 生成答案；
4. 保存 Agent 回复并返回稳定的 ChatResponse。

为什么单独抽这个服务：

- HTTP Router 只应该负责协议转换，不应该知道 Agent、Memory、Persistence 的串联顺序；
- AgentExecutionService 只应该负责“调用 Agent 图”，不应该负责会话和记忆；
- Memory Service 可以本地调用，也可以 HTTP 调用，Chat Turn 只依赖稳定 Protocol。
"""

from __future__ import annotations

import asyncio
from safemeal.application.agent.execution_service import AgentExecutionService
from safemeal.application.agent.context.builder import AgentContextBuilder
from safemeal.application.use_cases.chat.turn_persistence import (
    ChatTurnPersistence,
)
from safemeal.application.use_cases.chat.chat_exceptions import (
    ChatAgentUnavailableError,
)
from safemeal.application.contracts.chat_turn import ChatRequest, ChatResponse


class ChatTurnService:
    """编排一次用户聊天请求的应用服务。

    Args:
        persistence: 会话与消息持久化服务。
        agent_execution_service: 本地 Agent 图执行服务。
        context_builder: Agent 输入上下文构建器。
    """

    def __init__(
        self,
        *,
        persistence: ChatTurnPersistence,
        agent_execution_service: AgentExecutionService,
        context_builder: AgentContextBuilder,
    ) -> None:
        self._persistence = persistence
        self._agent_execution_service = agent_execution_service
        self._context_builder = context_builder

    async def handle(self, request: ChatRequest) -> ChatResponse:
        """处理一轮 Chat 请求。

        Args:
            request: HTTP 层传入的稳定 Chat 请求契约。

        Returns:
            可以直接返回给 HTTP 客户端的稳定 Chat 响应契约。
        """

        # start_turn 是同步数据库事务；放入线程，避免阻塞 FastAPI 的异步事件循环。
        # 它会在一个事务中完成：创建/复用 session、读取历史、保存用户问题。
        turn = await asyncio.to_thread(
            self._persistence.start_turn,
            request.session_id,
            request.user_id,
            request.message,
            request_id=request.request_id,
        )

        try:
            context = await asyncio.to_thread(
                self._context_builder.build_chat_context,
                user_id=request.user_id,
                message=request.message,
                session_id=turn.session_id,
                conversation_history=turn.history,
                source_message_id=str(turn.user_message_id),
            )

            # AgentExecutionService 只处理请求策略与 Agent 图执行。
            result = await self._agent_execution_service.process(
                request.message,
                turn.session_id,
                context=context,
            )

            if result.status == "error":
                await asyncio.to_thread(
                    self._persistence.save_agent_error,
                    session_id=turn.session_id,
                    user_id=request.user_id,
                    user_message_id=turn.user_message_id,
                    response_order_index=turn.response_order_index,
                    error_code=result.error_code,
                )
                raise ChatAgentUnavailableError(error_code=result.error_code)

            # Agent 回复落库同样是同步数据库事务，放入线程执行。
            message_id = await asyncio.to_thread(
                self._persistence.save_agent_response,
                session_id=turn.session_id,
                user_id=request.user_id,
                user_message_id=turn.user_message_id,
                response_order_index=turn.response_order_index,
                response=result.message,
                route=result.route,
                route_logic=result.route_logic,
                sources=result.sources,
                metadata=result.metadata,
            )
        except ChatAgentUnavailableError:
            raise
        except Exception:
            # The Agent call cannot share a transaction with an external model.
            # Marking the durable user turn failed makes the same request_id
            # explicitly retryable instead of leaving it permanently in progress.
            try:
                await asyncio.to_thread(
                    self._persistence.mark_turn_failed,
                    session_id=turn.session_id,
                    user_id=request.user_id,
                    user_message_id=turn.user_message_id,
                )
            except Exception:
                # Preserve the original failure; persistence diagnostics are logged
                # by the outer application boundary.
                pass
            raise

        return ChatResponse(
            message=result.message,
            session_id=turn.session_id,
            message_id=message_id,
            route=result.route,
            route_logic=result.route_logic,
            sources=result.sources,
            metadata=result.metadata,
            recipe=result.recipe,
        )
