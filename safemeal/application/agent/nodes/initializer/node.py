"""LangGraph 初始化节点。

本模块只服务于 Initializer 节点：从消息和可信 AgentContext 构建本轮问题、
对话历史、饮食约束及初始 Observation。
"""

from collections.abc import Sequence

from safemeal.application.contracts.agent.state import (
    AgentState,
    AgentStateUpdate,
    MessageInput,
)
from safemeal.application.contracts.agent.decisions import Observation
from safemeal.application.observability import trace_span
from safemeal.modules.dietary_safety.dietary_constraints import (
    DietaryConstraint,
    dietary_constraint_from_user_memories,
    extract_contextual_dietary_constraint,
    merge_dietary_constraints,
)
from safemeal.application.contracts.agent.context import AgentContext
from safemeal.shared.types import to_json_object

from .observations import (
    build_dietary_context_observation,
    build_user_memory_observation,
)


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
    return [Observation.model_validate(item) for item in agent_context.observations]


def build_initial_agent_state(
    messages: Sequence[MessageInput],
    user_memories: list[dict],
    conversation_history: list[dict[str, str]] | None = None,
    *,
    history_messages: int = 12,
):
    """Build the state fields owned by the Initializer node."""

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
        _build_initial_observations(user_memories, dietary_constraint),
    )


def create_initializer_node(
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
            if agent_context.dietary_constraints is not None:
                dietary_constraint = merge_dietary_constraints(
                    [
                        dietary_constraint,
                        DietaryConstraint.model_validate(
                            agent_context.dietary_constraints
                        ),
                    ],
                    strictness="hard_exclusion",
                )
                initial_observations = _build_initial_observations(
                    user_memories, dietary_constraint
                )
            task_payload = {
                "intent": agent_context.intent,
                "profile": agent_context.user_profile,
            }
            initial_observations.append(
                Observation(
                    call_id="task_context",
                    tool_name="task_context",
                    purpose="本轮任务与偏好",
                    success_criteria="在硬约束内满足本轮要求",
                    ok=True,
                    has_data=True,
                    summary=str(task_payload),
                    data=to_json_object(task_payload),
                )
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
                "direct_answer": "",
                "planning_rationale": "",
                "reflection_rationale": "",
                "sources": [],
                "human_approved": False,
                "approval_required": False,
                "safety_gate_blocked": False,
            }
            span.set_output(output)
            return output

    return initialize


__all__ = ["build_initial_agent_state", "create_initializer_node"]
