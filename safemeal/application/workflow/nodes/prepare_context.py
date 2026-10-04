"""Prepare history and memories once, before resolving this turn's requirements."""

import asyncio

from safemeal.application.contracts.workflow.models import WorkflowState
from safemeal.application.service.chat.request_understanding import (
    RequestUnderstandingService,
)
from safemeal.application.streaming import emit_workflow_progress
from safemeal.application.workflow.context.builder import AgentContextBuilder


class PrepareContextNode:
    def __init__(self, builder: AgentContextBuilder):
        self.builder = builder

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        await emit_workflow_progress(
            "prepare_context", "正在加载历史与饮食记忆并整理上下文"
        )
        request = state["request"]
        frame = state.get("request_frame")
        if frame is None:
            # Keeps the node usable in isolation. The compiled workflow always
            # supplies the frame from understand_request before reaching here.
            frame = RequestUnderstandingService().understand(request.message)
        safety_tasks = {
            "recipe_recommendation",
            "recipe_generation",
            "replace",
            "food_safety",
        }
        needs = set(frame.context_needs)
        if frame.primary_task in safety_tasks or frame.understanding_status != "accepted":
            needs.update({"allergies", "dietary_restrictions"})
        frame = frame.model_copy(update={"context_needs": tuple(sorted(needs))})
        context = await asyncio.to_thread(
            self.builder.build_chat_context,
            user_id=request.user_id,
            message=request.message,
            session_id=request.session_id,
            conversation_history=request.history
            or (request.context.conversation_history if request.context else []),
            source_message_id=request.source_message_id,
            use_user_memory=request.use_user_memory,
            request_frame=frame,
            preloaded_history=state.get("recent_history"),
        )
        if request.context:
            supplied = request.context.model_copy(deep=True)
            context.observations.extend(supplied.observations)
            context.user_memories.extend(supplied.user_memories)
            context.episodic_memories.extend(supplied.episodic_memories)
            context.context_metadata = {
                **supplied.context_metadata,
                **context.context_metadata,
            }
            context.user_profile = supplied.user_profile
            context.dietary_constraints = supplied.dietary_constraints
            context.requirements = supplied.requirements
        context.context_metadata.update(
            {
                "request_understanding_backend": frame.backend,
                "request_understanding_confidence": frame.confidence,
                "understanding_status": frame.understanding_status,
                "request_tasks": [task.kind for task in frame.tasks],
                "context_needs": list(frame.context_needs),
                "fallback_used": frame.fallback_used,
            }
        )
        return {"context": context, "request_frame": frame}
