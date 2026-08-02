"""Agent 图编排。

这里定义计划、执行、观察、反思和回答的闭环流程，是 Orchestrator 的核心
运行图。外部资源通过端口或注册表注入，不在图内直接创建。
"""

from collections.abc import Sequence
from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from safemeal.application.observability import trace_span
from safemeal.modules.dietary_safety.application import (
    dietary_constraint_from_user_memories,
    extract_contextual_dietary_constraint,
    merge_dietary_constraints,
)
from safemeal.application.agents.context import (
    build_dietary_context_observation,
    build_user_memory_observation,
)
from safemeal.application.agents.models import Observation
from safemeal.shared.types import to_json_object
from safemeal.shared.contracts.agent_context import AgentContext
from .decision_engine import DecisionEngine
from .nodes import (
    create_executor_node,
    create_planner_node,
    create_reflector_node,
    create_responder_node,
    observe,
)
from .state import AgentInputState, AgentState, AgentStateUpdate, MessageInput
from .tool_registry import ToolRegistry


def _question_from_messages(messages: Sequence[MessageInput]) -> str:
    if not messages:
        return ""
    message = messages[-1]
    if isinstance(message, dict):
        return str(message.get("content", ""))
    return str(getattr(message, "content", ""))


def _conversation_from_messages(
    messages: Sequence[MessageInput],
    limit: int = 12,
) -> list[dict[str, str]]:
    if limit <= 0:
        return []
    history = []
    for message in messages[-(limit + 1) : -1]:
        if isinstance(message, dict):
            role = str(message.get("role") or message.get("type") or "unknown")
            content = str(message.get("content", ""))
        else:
            role = str(getattr(message, "type", "unknown"))
            content = str(getattr(message, "content", ""))
        if content.strip():
            history.append({"role": role, "content": content})
    return history


def _resolve_dietary_constraint(
    question: str,
    conversation_history: list[dict[str, str]],
    user_memories: list[dict],
):
    contextual_dietary_constraint = extract_contextual_dietary_constraint(
        question,
        conversation_history,
    )
    memory_dietary_constraint = dietary_constraint_from_user_memories(user_memories)
    if contextual_dietary_constraint.strictness == "not_applicable_negated_constraint":
        return contextual_dietary_constraint
    return merge_dietary_constraints(
        [memory_dietary_constraint, contextual_dietary_constraint],
        strictness=(
            "hard_exclusion_with_long_term_memory"
            if memory_dietary_constraint.active
            else contextual_dietary_constraint.strictness
        ),
    )


def _build_initial_observations(user_memories: list[dict], dietary_constraint) -> list:
    user_memory_observation = build_user_memory_observation(user_memories)
    dietary_context_observation = build_dietary_context_observation(
        dietary_constraint,
    )
    return [
        item
        for item in (user_memory_observation, dietary_context_observation)
        if item is not None
    ]


def _context_observations(agent_context: AgentContext) -> list[Observation]:
    observations: list[Observation] = []
    for item in agent_context.observations:
        observations.append(Observation.model_validate(item))
    return observations


def build_initial_agent_state(
    messages: Sequence[MessageInput],
    user_memories: list[dict],
    conversation_history: list[dict[str, str]] | None = None,
    *,
    history_messages: int = 12,
):
    question = _question_from_messages(messages)
    resolved_history = (
        conversation_history
        if conversation_history is not None
        else _conversation_from_messages(messages, history_messages)
    )
    dietary_constraint = _resolve_dietary_constraint(
        question,
        resolved_history,
        user_memories,
    )
    return (
        question,
        resolved_history,
        dietary_constraint,
        _build_initial_observations(
            user_memories,
            dietary_constraint,
        ),
    )


def create_initialize_node(
    *,
    max_iterations: int,
    history_messages: int,
    max_tool_calls: int,
    max_model_tokens: int,
    max_model_cost: float,
):
    async def initialize(state: AgentState) -> AgentStateUpdate:
        with trace_span(
            "agent_node",
            "initialize",
            {"message_count": len(state.get("messages", []))},
        ) as span:
            messages = state.get("messages", [])
            agent_context = AgentContext.model_validate(
                state.get("agent_context") or {}
            )
            user_memories = agent_context.user_memories
            (
                question,
                conversation_history,
                dietary_constraint,
                initial_observations,
            ) = build_initial_agent_state(
                messages,
                user_memories,
                agent_context.conversation_history or None,
                history_messages=history_messages,
            )
            initial_observations = [
                *initial_observations,
                *_context_observations(agent_context),
            ]
            output: AgentStateUpdate = {
                "agent_context": to_json_object(agent_context),
                "question": question,
                "conversation_history": conversation_history,
                "pending_calls": [],
                "tool_results": [],
                "observations": initial_observations,
                "iteration": 0,
                "max_iterations": max_iterations,
                "evidence_sufficient": False,
                "missing_information": [],
                # LangGraph state 只传递 JSON DTO，不直接传递 Pydantic 领域对象。
                "dietary_constraints": to_json_object(dietary_constraint),
                "route": "plan",
                "executed_call_signatures": [],
                "tool_call_count": 0,
                "max_tool_calls": max_tool_calls,
                "max_model_tokens": max_model_tokens,
                "max_model_cost": max_model_cost,
                "budget_exhausted": False,
                "loop_stop_reason": "",
            }
            span.set_output(output)
            return output

    return initialize


def _after_plan(state: AgentState) -> Literal["execute_tools", "respond"]:
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
    engine: DecisionEngine,
    registry: ToolRegistry,
    checkpointer: BaseCheckpointSaver[Any] | Literal[False] | None = None,
    max_iterations: int = 4,
    history_messages: int = 12,
    max_tool_calls: int = 12,
    max_model_tokens: int = 20_000,
    max_model_cost: float = 0.0,
):
    builder = StateGraph(AgentState, input=AgentInputState)
    builder.add_node(
        "initialize",
        create_initialize_node(
            max_iterations=max_iterations,
            history_messages=history_messages,
            max_tool_calls=max_tool_calls,
            max_model_tokens=max_model_tokens,
            max_model_cost=max_model_cost,
        ),
    )
    builder.add_node("planner", create_planner_node(engine, registry))
    builder.add_node("execute_tools", create_executor_node(registry))
    builder.add_node("observe", observe)
    builder.add_node("reflect", create_reflector_node(engine, registry))
    builder.add_node("respond", create_responder_node(engine))

    builder.add_edge(START, "initialize")
    builder.add_edge("initialize", "planner")
    builder.add_conditional_edges("planner", _after_plan)
    builder.add_edge("execute_tools", "observe")
    builder.add_edge("observe", "reflect")
    builder.add_conditional_edges("reflect", _after_reflection)
    builder.add_edge("respond", END)
    return builder.compile(checkpointer=checkpointer)
