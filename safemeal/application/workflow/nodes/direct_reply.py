from safemeal.application.contracts.agent.api import AgentProcessResponse
from safemeal.application.contracts.workflow.models import WorkflowState


async def direct_reply(state: WorkflowState) -> WorkflowState:
    decision = state["intent"]
    message = decision.clarification or (
        "已识别本轮饮食偏好。"
        if decision.kind == "memory"
        else "我可以帮助你查询、推荐和生成食谱，或解答烹饪与食材问题。"
    )
    return {
        "result": AgentProcessResponse(
            message=message, route=decision.kind, route_logic="chat_workflow"
        )
    }
