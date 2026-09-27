from safemeal.application.observability.streaming import emit_workflow_progress
import asyncio
from safemeal.application.contracts.agent.context import AgentContext
from safemeal.application.contracts.workflow.models import WorkflowState
from safemeal.application.workflow.context.builder import AgentContextBuilder


class LoadMemoryNode:
    def __init__(self, builder: AgentContextBuilder):
        self.builder = builder

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        await emit_workflow_progress("load_memory", "正在加载饮食记忆")
        request = state["request"]
        if request.use_user_memory:
            context = await asyncio.to_thread(
                self.builder.build_chat_context,
                user_id=request.user_id,
                message=request.message,
                session_id=request.session_id,
                conversation_history=request.history
                or (request.context.conversation_history if request.context else []),
                source_message_id=request.source_message_id,
            )
            if request.context:
                # Explicit caller observations and preferences survive memory enrichment.
                context.observations.extend(request.context.observations)
                context.user_memories.extend(request.context.user_memories)
                context.episodic_memories.extend(request.context.episodic_memories)
                context.context_metadata = {
                    **request.context.context_metadata,
                    **context.context_metadata,
                }
                context.user_profile = request.context.user_profile
                context.dietary_constraints = request.context.dietary_constraints
        else:
            context = (
                request.context.model_copy(deep=True)
                if request.context
                else AgentContext(conversation_history=request.history)
            )
        context.context_metadata.update(
            user_id=request.user_id, session_id=request.session_id
        )
        return {"context": context, "safety_blocked": False}
