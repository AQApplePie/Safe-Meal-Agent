"""调用 Agent 前分别解析用户偏好、过敏和饮食限制。"""

from safemeal.agent.workflow.streaming import emit_workflow_progress
from safemeal.agent.contracts.workflow.models import WorkflowState
from safemeal.agent.safety.dietary_safety_service import (
    DietarySafetyService,
    hard_constraints,
)
from safemeal.modules.dietary.application.constraints import (
    dietary_constraint_from_values,
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
            if item.kind in {"food_category", "avoid_food_category"}:
                continue
            parsed = dietary_constraint_from_values(
                [item.value],
                trigger_term="过敏" if item.kind == "allergy" else "不能吃",
                strictness="request_frame_hard_exclusion",
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
    context.resolved_constraints = requirements.resolved.model_copy(deep=True)
    context.dietary_constraints = hard_constraints(requirements).model_dump(mode="json")
    return {
        "context": context,
        "requirements": requirements,
        "resolved_constraints": requirements.resolved,
    }
