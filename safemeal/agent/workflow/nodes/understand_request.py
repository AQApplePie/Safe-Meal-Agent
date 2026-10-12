"""在加载长期用户上下文前建立本轮请求契约。"""

from __future__ import annotations

from safemeal.agent.contracts.workflow.models import WorkflowState
from safemeal.shared.contracts.request_frame import (
    RequestFrame,
    RequestTask,
)
from safemeal.agent.understanding.port import RequestUnderstandingGateway
from safemeal.agent.understanding.request_understanding import (
    RequestUnderstandingService,
    RuleBasedRequestUnderstandingGateway,
)
from safemeal.agent.workflow.streaming import emit_workflow_progress
from safemeal.agent.workflow.context.builder import AgentContextBuilder


# 类说明（业务或基础设施实现类）：UnderstandRequestNode
# 作用：实现Workflow 请求理解节点，封装该组件的业务处理与依赖协作。
class UnderstandRequestNode:
    # 方法说明：__init__
    # 作用：初始化Workflow 请求理解节点，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   gateway（RequestUnderstandingGateway | None）：语言模型调用能力。
    #   context_builder（AgentContextBuilder）：Agent 上下文构建器。
    #   confidence_threshold（float）：请求理解结果允许进入执行流程的最低置信度；默认值为 0.7。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(
        self,
        gateway: RequestUnderstandingGateway | None,
        context_builder: AgentContextBuilder,
        *,
        confidence_threshold: float = 0.7,
    ) -> None:
        # 实例属性说明：_gateway
        # 作用：语言模型调用能力。
        self._gateway = gateway or RuleBasedRequestUnderstandingGateway()
        # 实例属性说明：_fallback
        # 作用：当前值不可用时使用的回退值。
        self._fallback = RequestUnderstandingService()
        # 实例属性说明：_context_builder
        # 作用：Agent 上下文构建器。
        self._context_builder = context_builder
        # 实例属性说明：_threshold
        # 作用：请求理解结果允许进入执行流程的最低置信度。
        self._threshold = confidence_threshold

    # 方法说明：__call__
    # 作用：执行Workflow 请求理解节点，按当前图状态返回节点更新。
    # 入参：
    #   state（WorkflowState）：聊天 Workflow 完整状态。
    # 出参：WorkflowState；聊天 Workflow 完整状态。
    async def __call__(self, state: WorkflowState) -> WorkflowState:
        await emit_workflow_progress(
            "understand_request", "正在识别任务、实体与上下文需求"
        )
        request = state["request"]
        fallback_history = request.history or (
            request.context.conversation_history if request.context else []
        )
        history, active_menu = self._context_builder.load_context_sources(
            user_id=request.user_id,
            session_id=request.session_id,
            source_message_id=request.source_message_id,
            fallback=fallback_history,
        )
        recent = history[-6:]
        try:
            frame = await self._gateway.understand(request.message, recent)
        except Exception as gateway_error:
            try:
                frame = self._fallback.understand(request.message, recent).model_copy(
                    update={
                        "backend": f"{getattr(self._gateway, 'backend_name', 'unknown')}:rules_fallback",
                        "understanding_status": "fallback",
                        "fallback_used": True,
                        "validation_errors": (type(gateway_error).__name__,),
                    }
                )
            except Exception as fallback_error:
                # 无法校验的理解结果转成可观察的澄清状态，不能直接抛出 HTTP 500。
                frame = RequestFrame(
                    tasks=(RequestTask(kind="clarify"),),
                    confidence=0.0,
                    understanding_status="incomplete",
                    backend=f"{getattr(self._gateway, 'backend_name', 'unknown')}:invalid",
                    fallback_used=True,
                    clarification_question="我还不能可靠理解这次用餐安排，请补充希望的菜品数量或类型。",
                    validation_errors=(
                        type(gateway_error).__name__,
                        type(fallback_error).__name__,
                    ),
                )
        if frame.confidence < self._threshold:
            frame = frame.model_copy(
                update={
                    "understanding_status": "low_confidence",
                    "fallback_used": True,
                }
            )
        return {
            "request_frame": frame,
            "recent_history": history,
            "active_menu": active_menu,
        }


__all__ = ["UnderstandRequestNode"]
