"""Independent, fail-closed final publication gate."""

from safemeal.application.observability.streaming import emit_workflow_progress
from safemeal.application.contracts.workflow.models import WorkflowState
from safemeal.application.contracts.agent.decisions import Observation
from safemeal.modules.dietary_safety.dietary_constraints import (
    DietaryConstraint,
    build_dietary_safety_result,
)
from safemeal.modules.dietary_safety.answer import render_dietary_safety_answer
from safemeal.modules.dietary_safety.generated_safety import generated_recipe_violations


async def check_final_safety(state: WorkflowState) -> WorkflowState:
    await emit_workflow_progress("final_safety", "正在复核食材与饮食限制")
    result = state["result"].model_copy(deep=True)
    constraint = DietaryConstraint.model_validate(
        state["context"].dietary_constraints or {"active": False}
    )
    if (
        result.metadata.get("approval_required")
        or result.metadata.get("approved") is False
    ):
        result.recipe = None
        result.sources = []
        result.metadata.pop("generated_recipe", None)
        result.message = (
            "操作已暂停，等待人工确认后继续执行。"
            if result.metadata.get("approval_required")
            else "操作已由人工拒绝，未执行相关工具。"
        )
        result.metadata["safety_review"] = "no_recommendation"
        return {"result": result, "safety_blocked": False}
    if result.status == "error" or not constraint.active:
        result.metadata["safety_review"] = (
            "not_applicable" if not constraint.active else "agent_failed"
        )
        return {"result": result, "safety_blocked": False}
    if state["intent"].kind in {"memory", "clarify", "out_of_scope"}:
        result.metadata["safety_review"] = "no_recommendation"
        return {"result": result, "safety_blocked": False}
    observations = [Observation.model_validate(item) for item in result.evidence]
    # Re-evaluate source evidence; never trust an Agent's claimed safety verdict.
    observations = [
        o
        for o in observations
        if o.tool_name
        not in {
            "dietary_safety_filter",
            "dietary_context",
            "user_memory_context",
            "multi_route_retrieval",
        }
    ]
    safety = build_dietary_safety_result(
        constraint=constraint, observations=observations
    )
    if result.recipe is not None:
        violations = generated_recipe_violations(
            result.recipe, constraint.excluded_ingredients
        )
        allowed = {item.name for item in safety.safe_recipes}
        if violations or result.recipe.name not in allowed:
            safety.safe_recipes = [
                item for item in safety.safe_recipes if item.name != result.recipe.name
            ]
            result.recipe = None
    result.metadata.pop("generated_recipe", None)
    reviewed = Observation(
        call_id="workflow_safety",
        tool_name="dietary_safety_filter",
        purpose="最终过敏复核",
        success_criteria="仅发布通过复核的食谱",
        ok=True,
        has_data=True,
        summary="Final workflow safety review",
        data=safety.model_dump(mode="json"),
    )
    result.message = render_dietary_safety_answer([reviewed])
    blocked = not safety.safe_recipes
    result.metadata["safety_review"] = "blocked" if blocked else "passed"
    result.metadata["safe_recipe_names"] = [item.name for item in safety.safe_recipes]
    if blocked:
        result.status = "degraded"
        result.error_code = "insufficient_safety_evidence"
        result.sources = []
    return {"result": result, "safety_blocked": blocked}
