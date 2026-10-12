"""协调单轮聊天的持久化与工作流执行。"""

from __future__ import annotations

import asyncio
from safemeal.agent.contracts.api import AgentResumeRequest, AgentProcessResponse
from safemeal.agent.workflow.runner import ChatWorkflow
from safemeal.agent.contracts.workflow.models import WorkflowRequest
from safemeal.modules.conversation.application.turn_persistence import (
    ChatTurnPersistence,
)
from safemeal.modules.conversation.application.chat_exceptions import (
    ChatAgentUnavailableError,
)
from safemeal.modules.conversation.contracts.chat.turn import ChatRequest, ChatResponse


# 类说明（业务或基础设施实现类）：ChatTurnService
# 作用：编排一次用户聊天请求的应用服务。
class ChatTurnService:
    """编排一次用户聊天请求的应用服务。

    Args:
        persistence: 会话与消息持久化服务。
        workflow: 独立聊天 Workflow 入口。
    """

    # 方法说明：__init__
    # 作用：初始化单轮聊天编排服务，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   persistence（ChatTurnPersistence）：聊天轮次与审批持久化业务组件。
    #   workflow（ChatWorkflow）：统一聊天 Workflow 执行入口。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(
        self,
        *,
        persistence: ChatTurnPersistence,
        workflow: ChatWorkflow,
    ) -> None:
        # 实例属性说明：_persistence
        # 作用：聊天轮次与审批持久化业务组件。
        self._persistence = persistence
        # 实例属性说明：_workflow
        # 作用：统一聊天 Workflow 执行入口。
        self._workflow = workflow

    # 方法说明：resume
    # 作用：从持久化中断状态恢复当前审批任务并整理执行结果。
    # 入参：
    #   request（AgentResumeRequest）：Agent 审批恢复请求。
    #   user_id（str）：经身份绑定后的持久化用户标识。
    # 出参：AgentProcessResponse；Agent 内部处理响应。
    async def resume(
        self, request: AgentResumeRequest, *, user_id: str
    ) -> AgentProcessResponse:
        previous = await asyncio.to_thread(
            self._persistence.claim_approval,
            session_id=request.session_id,
            user_id=user_id,
            message_id=request.message_id,
            approval_id=request.approval_id,
            approved=request.approved,
        )
        try:
            result = await self._workflow.resume(
                request.session_id, approved=request.approved
            )
        except Exception:
            await asyncio.to_thread(
                self._persistence.finish_approval,
                session_id=request.session_id,
                user_id=user_id,
                message_id=request.message_id,
                content="恢复中断，执行结果尚未确认。请勿重复执行此操作。",
                metadata={**previous, "approval_state": "failed"},
                failed=True,
            )
            raise
        result.metadata.update(
            {
                "session_id": request.session_id,
                "message_id": str(request.message_id),
                "approval_state": "failed"
                if result.status == "error"
                else (
                    "pending"
                    if result.metadata.get("approval_required")
                    else ("approved" if request.approved else "rejected")
                ),
                "previous_approval_id": request.approval_id,
            }
        )
        result.metadata["approval_history"] = previous.get("approval_history", [])
        if not result.metadata.get("approval_required"):
            result.metadata["approval_id"] = request.approval_id
            result.metadata["approval_required"] = False
        await asyncio.to_thread(
            self._persistence.finish_approval,
            session_id=request.session_id,
            user_id=user_id,
            message_id=request.message_id,
            content=result.message,
            metadata={
                **result.metadata,
                "route": result.route,
                "route_logic": result.route_logic,
                "sources": [s.model_dump(mode="json") for s in result.sources],
                "recipe": result.recipe.model_dump(mode="json")
                if result.recipe
                else None,
            },
            failed=result.status == "error",
        )
        return result

    # 方法说明：handle
    # 作用：处理一轮 Chat 请求。
    # 入参：
    #   request（ChatRequest）：用户聊天请求。
    # 出参：ChatResponse；用户聊天响应。
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
            try:
                await asyncio.to_thread(
                    self._persistence.mark_turn_failed,
                    session_id=turn.session_id,
                    user_id=user_id,
                    user_message_id=turn.user_message_id,
                )
            except Exception:
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
