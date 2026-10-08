"""Agent 编排层运行图。

这里定义计划、执行、观察、反思和回答的闭环流程，是 Orchestrator 的核心
运行图。外部资源通过端口或注册表注入，不在图内直接创建。
"""

from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from .nodes.approval import create_approval_node

from safemeal.agent.runtime.model import AgentModelGateway
from safemeal.agent.runtime.aggregation import create_responder_node
from .nodes import (
    create_executor_node,
    create_initializer_node,
    create_planner_node,
    create_reflector_node,
    observe,
)
from safemeal.agent.contracts.state import AgentInputState, AgentState
from safemeal.agent.runtime.tools.ports.tool_executor import ToolExecutor


from .routing import _after_plan, _after_approval, _after_reflection


def build_agent_graph(
    *,
    model_gateway: AgentModelGateway,
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
    builder.add_node(
        "human_approval",
        create_approval_node(approval_tool_names),
    )
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
    builder.add_conditional_edges(
        "reflect",
        _after_reflection,
        {"execute_tools": "human_approval", "planner": "planner", "respond": "respond"},
    )
    builder.add_edge("respond", END)
    return builder.compile(checkpointer=checkpointer)
