"""Agent 图的条件路由规则。"""

from typing import Literal
from safemeal.agent.contracts.state import AgentState


def _after_plan(state: AgentState) -> Literal["execute_tools", "respond"]:
    return "execute_tools" if state.get("pending_calls") else "respond"


def _after_approval(state: AgentState) -> Literal["execute_tools", "respond"]:
    return "execute_tools" if state.get("pending_calls") else "respond"


def _after_reflection(
    state: AgentState,
) -> Literal["execute_tools", "planner", "respond"]:
    route = state.get("route")
    if route == "continue" and state.get("pending_calls"):
        return "execute_tools"
    if route == "replan":
        return "planner"
    return "respond"
