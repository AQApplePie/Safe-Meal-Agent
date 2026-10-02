"""Agent invocation through an application port, never graph internals."""

from safemeal.application.streaming import emit_workflow_progress
from safemeal.application.contracts.workflow.models import WorkflowState
from safemeal.application.ports.agent import AgentInvoker
from safemeal.application.streaming import suppress_answer_stream


class InvokeAgentNode:
    def __init__(self, agent: AgentInvoker):
        self.agent = agent

    async def __call__(self, state: WorkflowState) -> WorkflowState:
        await emit_workflow_progress("invoke_agent", "正在查找和整理食谱")
        request = state["request"]
        # Drafts are private until the workflow's final safety check completes.
        with suppress_answer_stream():
            result = await self.agent.process(
                request.message,
                request.session_id,
                context=state["context"].model_copy(deep=True),
            )
        result = result.model_copy(deep=True)
        for key in (
            "request_understanding_backend",
            "request_understanding_confidence",
            "understanding_status",
            "request_tasks",
            "context_needs",
            "fallback_used",
            "loaded_context_types",
        ):
            value = state["context"].context_metadata.get(key)
            if value is not None:
                result.metadata[key] = value
        return {"result": result}
