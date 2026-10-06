"""LangGraph 初始化节点。

本模块只服务于 Initializer 节点：从消息和可信 AgentContext 构建本轮问题、
对话历史、饮食约束及初始 Observation。
"""

from collections.abc import Sequence
from safemeal.application.service.dietary_safety.dietary_safety_service import (
    DietarySafetyService,
    hard_constraints,
)

from safemeal.application.contracts.agent.state import (
    AgentState,
    AgentStateUpdate,
    MessageInput,
)
from safemeal.application.contracts.agent.decisions import Observation
from safemeal.application.contracts.agent.context import AgentContext
from safemeal.shared.types import to_json_object

from safemeal.application.agent.memory.context import build_memory_observations
from safemeal.application.contracts.agent.menu_planning import initialize_menu_task


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


def _context_observations(agent_context: AgentContext) -> list[Observation]:
    return [Observation.model_validate(item) for item in agent_context.observations]


def create_initializer_node(
    *,
    max_iterations: int,
    history_messages: int,
    max_tool_calls: int,
    max_model_tokens: int,
    max_model_cost: float,
):
    async def initialize(state: AgentState) -> AgentStateUpdate:
        messages = state.get("messages", [])
        agent_context = AgentContext.model_validate(state.get("agent_context") or {})
        question = _question_from_messages(messages)
        conversation_history = (
            agent_context.conversation_history
            or _conversation_from_messages(messages, history_messages)
        )
        if agent_context.requirements is None:
            agent_context.requirements = DietarySafetyService().resolve_constraints(
                question, conversation_history, agent_context
            )
        dietary_constraint = hard_constraints(agent_context.requirements)
        agent_context.dietary_constraints = dietary_constraint.model_dump(mode="json")


        initial_observations = build_memory_observations(
            agent_context, dietary_constraint
        )
        menu_execution_plan = None
        menu_task_progress = None
        if (
            agent_context.request_frame is not None
            and agent_context.request_frame.menu_planning is not None
        ):
            plan, progress = initialize_menu_task(
                agent_context.request_frame.menu_planning,
                scenario=agent_context.request_frame.scenario,
            )
            menu_execution_plan = plan.model_dump(mode="json")
            modification = agent_context.context_metadata.get("menu_modification")
            if isinstance(modification, dict):
                progress = progress.model_copy(
                    update={
                        "excluded_recipe_ids": tuple(
                            int(item)
                            for item in modification.get("exclude_recipe_ids", [])
                        ),
                        "excluded_recipe_names": tuple(
                            str(item)
                            for item in modification.get("exclude_recipe_names", [])
                        ),
                    }
                )
            menu_task_progress = progress.model_dump(mode="json")
        task_payload = {
            "intent": agent_context.intent,
            "profile": agent_context.user_profile,
            "requirements": agent_context.requirements.model_dump(mode="json"),
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
            "intent": None,
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
            "menu_execution_plan": to_json_object(menu_execution_plan or {}),
            "menu_task_progress": to_json_object(menu_task_progress or {}),
            "tool_trace": [],
        }
        return output

    return initialize


__all__ = ["create_initializer_node"]
