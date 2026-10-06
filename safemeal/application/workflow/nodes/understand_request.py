"""在加载长期用户上下文前建立本轮请求契约。"""

from __future__ import annotations

from safemeal.application.contracts.workflow.models import WorkflowState
from safemeal.application.contracts.workflow.request_frame import (
    RequestFrame,
    RequestTask,
)
from safemeal.application.ports.request_understanding import RequestUnderstandingGateway
from safemeal.application.service.chat.request_understanding import (
    RequestUnderstandingService,
    RuleBasedRequestUnderstandingGateway,
)
from safemeal.application.streaming import emit_workflow_progress
from safemeal.application.workflow.context.builder import AgentContextBuilder


class UnderstandRequestNode:
    def __init__(
        self,
        gateway: RequestUnderstandingGateway | None,
        context_builder: AgentContextBuilder,
        *,
        confidence_threshold: float = 0.7,
    ) -> None:
        self._gateway = gateway or RuleBasedRequestUnderstandingGateway()
        self._fallback = RequestUnderstandingService()
        self._context_builder = context_builder
        self._threshold = confidence_threshold

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        await emit_workflow_progress(
            "understand_request", "正在识别任务、实体与上下文需求"
        )
        request = state["request"]
        fallback_history = request.history or (
            request.context.conversation_history if request.context else []
        )
        history = self._context_builder.load_recent_history(
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
        return {"request_frame": frame, "recent_history": history}


__all__ = ["UnderstandRequestNode"]
