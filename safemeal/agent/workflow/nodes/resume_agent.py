from safemeal.agent.workflow.streaming import emit_workflow_progress
from safemeal.agent.contracts.workflow.models import (
    WorkflowState,
    WorkflowRequest,
)
from safemeal.agent.contracts.ports import ResumableAgent
from safemeal.agent.workflow.streaming import suppress_answer_stream


class ResumeAgentNode:
    def __init__(self, agent: ResumableAgent):
        self.agent = agent

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        await emit_workflow_progress("resume_agent", "正在恢复已确认的操作")
        request = state["request"]
        with suppress_answer_stream():
            resumed = await self.agent.resume(
                request.session_id, approved=bool(request.resume_approved)
            )
        return {
            "result": resumed.response,
            "context": resumed.context,
            "request": WorkflowRequest(
                message=resumed.message,
                session_id=request.session_id,
                user_id=str(
                    resumed.context.context_metadata.get("user_id") or "internal_user"
                ),
                context=resumed.context,
                use_user_memory=False,
                resume_approved=request.resume_approved,
            ),
        }
