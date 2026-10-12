"""Agent 图的条件路由规则。"""

from typing import Literal
from safemeal.agent.contracts.state import AgentState


# 方法说明：_after_plan
# 作用：依据规划结果选择审批、工具执行或直接回复分支。
# 入参：
#   state（AgentState）：Agent 完整图状态。
# 出参：Literal['execute_tools', 'respond']；允许值为 ('execute_tools', 'respond')。
def _after_plan(state: AgentState) -> Literal["execute_tools", "respond"]:
    return "execute_tools" if state.get("pending_calls") else "respond"


# 方法说明：_after_approval
# 作用：依据人工审批结果决定继续执行工具还是转入回复。
# 入参：
#   state（AgentState）：Agent 完整图状态。
# 出参：Literal['execute_tools', 'respond']；允许值为 ('execute_tools', 'respond')。
def _after_approval(state: AgentState) -> Literal["execute_tools", "respond"]:
    return "execute_tools" if state.get("pending_calls") else "respond"


# 方法说明：_after_reflection
# 作用：根据反思结果及循环上限决定重新规划还是完成回复。
# 入参：
#   state（AgentState）：Agent 完整图状态。
# 出参：Literal['execute_tools', 'planner', 'respond']；允许值为 ('execute_tools',
# 'planner', 'respond')。
def _after_reflection(
    state: AgentState,
) -> Literal["execute_tools", "planner", "respond"]:
    route = state.get("route")
    if route == "continue" and state.get("pending_calls"):
        return "execute_tools"
    if route == "replan":
        return "planner"
    return "respond"
