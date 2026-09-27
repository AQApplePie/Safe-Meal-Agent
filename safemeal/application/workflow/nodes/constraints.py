"""Resolve explicit turn constraints without rewriting long-term memory."""

from safemeal.application.observability.streaming import emit_workflow_progress
from safemeal.application.contracts.workflow.models import WorkflowState
from safemeal.modules.dietary_safety.dietary_constraints import (
    DietaryConstraint,
    dietary_constraint_from_user_memories,
    extract_contextual_dietary_constraint,
    merge_dietary_constraints,
)
from safemeal.modules.user_memory.memory_extraction import UserMemoryExtractor


async def resolve_constraints(state: WorkflowState) -> WorkflowState:
    await emit_workflow_progress("resolve_constraints", "正在核对本轮偏好与饮食限制")
    context = state["context"].model_copy(deep=True)
    message = state["request"].message
    constraints = [
        dietary_constraint_from_user_memories(context.user_memories),
        extract_contextual_dietary_constraint(
            message, state["request"].history or context.conversation_history
        ),
    ]
    if context.dietary_constraints is not None:
        constraints.append(
            DietaryConstraint.model_validate(context.dietary_constraints)
        )
    resolved = merge_dietary_constraints(
        constraints, strictness="workflow_hard_exclusion"
    )
    context.dietary_constraints = resolved.model_dump(mode="json")
    candidates = UserMemoryExtractor().extract(message).candidates
    context.user_profile = {
        **(context.user_profile or {}),
        "turn_preferences": [
            {"type": item.memory_type, "key": item.key, "value": item.value}
            for item in candidates
            if item.memory_type not in {"dietary_allergy", "dietary_restriction"}
        ],
    }
    return {"context": context}
