"""Map internal HTTP requests to workflow contracts without business rules."""

from safemeal.application.contracts.agent.api import AgentProcessRequest
from safemeal.application.contracts.workflow.models import WorkflowRequest


def to_workflow_request(request: AgentProcessRequest) -> WorkflowRequest:
    """Preserve explicit context and the legacy history fallback."""
    return WorkflowRequest(
        message=request.message,
        session_id=request.session_id,
        user_id=request.user_id,
        history=(
            request.context.conversation_history if request.context else request.history
        ),
        context=request.context,
        use_user_memory=request.use_user_memory,
        include_trace=request.include_trace,
    )
