"""Persist a chat turn around an independent chat workflow.

The workflow owns context, intent, Agent invocation and final safety review;
this service only owns the durable user/assistant turn lifecycle.
"""

from __future__ import annotations

import asyncio
from safemeal.application.workflow.runner import ChatWorkflow
from safemeal.application.contracts.workflow.models import WorkflowRequest
from safemeal.application.service.chat.turn_persistence import (
    ChatTurnPersistence,
)
from safemeal.application.service.chat.chat_exceptions import (
    ChatAgentUnavailableError,
)
from safemeal.application.contracts.chat.turn import ChatRequest, ChatResponse


class ChatTurnService:
    """编排一次用户聊天请求的应用服务。

    Args:
        persistence: 会话与消息持久化服务。
        workflow: 独立聊天 Workflow 入口。
    """

    def __init__(
        self,
        *,
        persistence: ChatTurnPersistence,
        workflow: ChatWorkflow,
    ) -> None:
        self._persistence = persistence
        self._workflow = workflow

    async def handle(self, request: ChatRequest) -> ChatResponse:
        """处理一轮 Chat 请求。

        Args:
            request: HTTP 层传入的稳定 Chat 请求契约。

        Returns:
            可以直接返回给 HTTP 客户端的稳定 Chat 响应契约。
        """

        user_id = request.user_id
        if not user_id:
            raise ValueError("ChatRequest.user_id must be bound by the caller")

        # start_turn 是同步数据库事务；放入线程，避免阻塞 FastAPI 的异步事件循环。
        # 它会在一个事务中完成：创建/复用 session、保存用户问题。
        turn = await asyncio.to_thread(
            self._persistence.start_turn,
            request.session_id,
            user_id,
            request.message,
            request_id=request.request_id,
        )

        try:
            result = await self._workflow.run(
                WorkflowRequest(
                    user_id=user_id,
                    message=request.message,
                    session_id=turn.session_id,
                    source_message_id=str(turn.user_message_id),
                )
            )

            if result.status == "error":
                await asyncio.to_thread(
                    self._persistence.save_agent_error,
                    session_id=turn.session_id,
                    user_id=user_id,
                    user_message_id=turn.user_message_id,
                    response_order_index=turn.response_order_index,
                    error_code=result.error_code,
                )
                raise ChatAgentUnavailableError(error_code=result.error_code)

            # Agent 回复落库同样是同步数据库事务，放入线程执行。
            message_id = await asyncio.to_thread(
                self._persistence.save_agent_response,
                session_id=turn.session_id,
                user_id=user_id,
                user_message_id=turn.user_message_id,
                response_order_index=turn.response_order_index,
                response=result.message,
                route=result.route,
                route_logic=result.route_logic,
                sources=result.sources,
                metadata={
                    **result.metadata,
                    "recipe": result.recipe.model_dump(mode="json")
                    if result.recipe
                    else None,
                },
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
                    user_id=user_id,
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
