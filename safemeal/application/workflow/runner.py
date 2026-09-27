"""Public chat workflow entry point, independent of Agent implementation."""

from safemeal.application.contracts.workflow.models import WorkflowRequest
from safemeal.application.contracts.agent.api import AgentProcessResponse
from safemeal.application.observability.streaming import suppress_answer_stream


class ChatWorkflow:
    def __init__(self, graph, resume_graph=None):
        self.graph = graph
        self.resume_graph = resume_graph

    async def run(self, request: WorkflowRequest) -> AgentProcessResponse:
        with suppress_answer_stream():
            state = await self.graph.ainvoke({"request": request})
        result = state["result"]
        result.metadata["agent_status"] = result.status
        # Evidence is an Agent-to-workflow contract, not a second unreviewed UI output.
        return result.model_copy(update={"evidence": []})

    async def resume(self, session_id: str, *, approved: bool) -> AgentProcessResponse:
        if self.resume_graph is None:
            raise RuntimeError("This workflow has no resumable Agent")
        with suppress_answer_stream():
            state = await self.resume_graph.ainvoke(
                {
                    "request": WorkflowRequest(
                        message="",
                        user_id="internal_user",
                        session_id=session_id,
                        use_user_memory=False,
                        resume_approved=approved,
                    )
                }
            )
        result = state["result"]
        result.metadata["agent_status"] = result.status
        # Evidence is an Agent-to-workflow contract, not a second unreviewed UI output.
        return result.model_copy(update={"evidence": []})
