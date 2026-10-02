"""Resolve separate user preferences and allergies before invoking the Agent."""

from safemeal.application.streaming import emit_workflow_progress
from safemeal.application.contracts.workflow.models import WorkflowState
from safemeal.application.service.dietary_safety.dietary_safety_service import (
    DietarySafetyService,
    hard_constraints,
)
from safemeal.application.service.dietary_safety.constraints import (
    extract_dietary_constraint,
    merge_dietary_constraints,
)


async def resolve_constraints(state: WorkflowState) -> WorkflowState:
    await emit_workflow_progress("resolve_constraints", "正在整理偏好、过敏与本轮要求")
    context = state["context"].model_copy(deep=True)
    request = state["request"]
    requirements = (
        context.requirements.model_copy(deep=True)
        if request.resume_approved is not None and context.requirements is not None
        else DietarySafetyService().resolve_constraints(
            request.message, context.conversation_history, context
        )
    )
    frame = state.get("request_frame") or context.request_frame
    if frame is not None and frame.current_constraints:
        allergy_constraints = [requirements.allergies]
        restriction_constraints = [requirements.restrictions]
        for item in frame.current_constraints:
            parsed = extract_dietary_constraint(
                f"对{item.value}过敏"
                if item.kind == "allergy"
                else f"不能吃{item.value}"
            )
            (
                allergy_constraints
                if item.kind == "allergy"
                else restriction_constraints
            ).append(parsed)
        requirements = requirements.model_copy(
            update={
                "allergies": merge_dietary_constraints(allergy_constraints),
                "restrictions": merge_dietary_constraints(restriction_constraints),
            }
        )
    context.requirements = requirements.model_copy(deep=True)
    context.dietary_constraints = hard_constraints(requirements).model_dump(mode="json")
    return {"context": context, "requirements": requirements}
