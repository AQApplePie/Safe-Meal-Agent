from langgraph.types import interrupt
from safemeal.agent.contracts.state import AgentState


# 方法说明：create_approval_node
# 作用：构造在受保护工具执行前暂停的人工审批节点。
# 入参：
#   tool_names（frozenset[str]）：允许使用的工具名称集合。
# 出参：按实现返回；绑定当前依赖的图节点函数，接收图状态并返回局部状态更新。
def create_approval_node(tool_names: frozenset[str]):
    # 方法说明：approve
    # 作用：处理人工审批决定，更新待执行工具计划。
    # 入参：
    #   state（AgentState）：Agent 完整图状态。
    # 出参：AgentState；Agent 完整图状态。
    def approve(state: AgentState) -> AgentState:
        pending = state.get("pending_calls", [])
        guarded = [call for call in pending if call.tool_name in tool_names]
        if not guarded:
            return {}
        decision = interrupt(
            {
                "kind": "human_approval",
                "message": "请确认是否执行高影响工具调用",
                "calls": [call.model_dump(mode="json") for call in guarded],
            }
        )
        approved = bool(
            decision.get("approved") is True
            if isinstance(decision, dict)
            else decision is True
        )
        return {
            "pending_calls": pending if approved else [],
            "direct_answer": (
                "操作已由人工拒绝，未执行相关工具。" if not approved else ""
            ),
        }

    return approve
