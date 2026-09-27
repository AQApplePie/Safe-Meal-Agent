from langgraph.types import interrupt
from safemeal.application.contracts.agent.state import AgentState


def create_approval_node(tool_names: frozenset[str]):
    def approve(state: AgentState) -> AgentState:
        pending = state.get("pending_calls", [])
        guarded = [call for call in pending if call.tool_name in tool_names]
        if not guarded:
            return {"human_approved": True, "approval_required": False}
        decision = interrupt(
            {
                "kind": "human_approval",
                "message": "请确认是否执行高影响工具调用",
                "calls": [call.model_dump(mode="json") for call in guarded],
            }
        )
        approved = bool(
            decision.get("approved") if isinstance(decision, dict) else decision
        )
        return {
            "human_approved": approved,
            "approval_required": True,
            "pending_calls": pending if approved else [],
            "direct_answer": (
                "操作已由人工拒绝，未执行相关工具。" if not approved else ""
            ),
        }

    return approve
