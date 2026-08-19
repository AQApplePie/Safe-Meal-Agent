"""Agent 图编排。

这里定义计划、执行、观察、反思和回答的闭环流程，是 Orchestrator 的核心
运行图。外部资源通过端口或注册表注入，不在图内直接创建。
"""

from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from safemeal.application.ports.llm.language_model_gateway import LanguageModelGateway
from .nodes import (
    create_executor_node,
    create_initializer_node,
    create_planner_node,
    create_reflector_node,
    create_responder_node,
    observe,
)
from safemeal.application.agent.utils.state import AgentInputState, AgentState
from safemeal.application.ports.tools.tool_executor import ToolExecutor


def _after_plan(state: AgentState) -> Literal["execute_tools", "respond"]:
    return "execute_tools" if state.get("pending_calls") else "respond"


def _approval_gate(tool_names: frozenset[str]):
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


def build_agent_graph(
    *,
    model_gateway: LanguageModelGateway,
    tool_executor: ToolExecutor,
    checkpointer: BaseCheckpointSaver[Any] | Literal[False] | None = None,
    max_iterations: int = 4,
    history_messages: int = 12,
    max_tool_calls: int = 12,
    max_model_tokens: int = 20_000,
    max_model_cost: float = 0.0,
    approval_tool_names: frozenset[str] = frozenset(),
):
    builder = StateGraph(AgentState, input=AgentInputState)
    builder.add_node(
        "initialize",
        create_initializer_node(
            max_iterations=max_iterations,
            history_messages=history_messages,
            max_tool_calls=max_tool_calls,
            max_model_tokens=max_model_tokens,
            max_model_cost=max_model_cost,
        ),
    )
    builder.add_node("planner", create_planner_node(model_gateway, tool_executor))
    builder.add_node("human_approval", _approval_gate(approval_tool_names))
    builder.add_node("execute_tools", create_executor_node(tool_executor))
    builder.add_node("observe", observe)
    builder.add_node("reflect", create_reflector_node(model_gateway, tool_executor))
    builder.add_node("respond", create_responder_node(model_gateway))

    builder.add_edge(START, "initialize")
    builder.add_edge("initialize", "planner")
    builder.add_conditional_edges(
        "planner",
        _after_plan,
        {"execute_tools": "human_approval", "respond": "respond"},
    )
    builder.add_conditional_edges("human_approval", _after_approval)
    builder.add_edge("execute_tools", "observe")
    builder.add_edge("observe", "reflect")
    builder.add_conditional_edges("reflect", _after_reflection)
    builder.add_edge("respond", END)
    return builder.compile(checkpointer=checkpointer)
