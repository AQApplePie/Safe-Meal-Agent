"""Review structured recipes against the unchanged pre-Agent requirements."""

from safemeal.application.streaming import emit_workflow_progress
from safemeal.application.contracts.workflow.models import WorkflowState
from safemeal.application.contracts.agent.decisions import Observation
from safemeal.application.service.dietary_safety.dietary_safety_service import (
    DietarySafetyService,
)
from safemeal.application.workflow.review_reply import render_review_reply

_RECIPE_TOOLS = {
    "search_recipes",
    "get_recipe",
    "recommend_recipes",
    "generate_recipe",
    "dietary_safe_recipe_query",
}


async def check_final_safety(state: WorkflowState) -> WorkflowState:
    await emit_workflow_progress("final_safety", "正在分别复核过敏限制与偏好满足情况")
    result = state["result"].model_copy(deep=True)
    result.metadata.pop("generated_recipe", None)
    if (
        result.metadata.get("approval_required")
        or result.metadata.get("approved") is False
    ):
        result.recipe = None
        result.sources = []
        result.message = (
            "操作已暂停，等待人工确认后继续执行。"
            if result.metadata.get("approval_required")
            else "操作已由人工拒绝，未执行相关工具。"
        )
        result.metadata["safety_review"] = "no_recommendation"
        return {"result": result}
    if result.status == "error":
        result.recipe = None
        result.sources = []
        result.metadata["safety_review"] = "agent_failed"
        return {"result": result}
    observations = []
    for payload in result.evidence:
        try:
            item = Observation.model_validate(payload)
        except ValueError:
            continue
        if item.tool_name in _RECIPE_TOOLS:
            observations.append(item)
    if (
        result.intent is not None
        and result.intent.kind in {"memory", "clarify", "out_of_scope", "knowledge"}
        and not observations
        and result.recipe is None
    ):
        result.metadata["safety_review"] = "no_recommendation"
        return {"result": result}
    # A card is a second publication surface. Compare it as additional evidence,
    # but never let a card alone manufacture a successful tool result.
    if result.recipe is not None:
        backed = any(
            o.ok
            and o.tool_name == "generate_recipe"
            and isinstance(o.data, dict)
            and o.data.get("name") == result.recipe.name
            for o in observations
        )
        if backed:
            observations.append(
                Observation(
                    call_id="returned_recipe_card",
                    tool_name="generate_recipe",
                    purpose="复核食谱卡片",
                    success_criteria="卡片与证据均满足要求",
                    ok=True,
                    has_data=True,
                    summary="returned recipe",
                    data=result.recipe.model_dump(mode="json"),
                )
            )
        else:
            result.recipe = None
    requirements = state["requirements"]
    review = DietarySafetyService().review_recipes(requirements, observations)
    if result.intent is not None and result.intent.kind == "recipe_detail":
        result.metadata["recipe_reviews"] = [
            item.model_dump(mode="json", exclude={"evidence"})
            for item in review.recipes
        ]
        excluded = [item for item in review.recipes if item.decision == "excluded"]
        unknown = [item for item in review.recipes if item.decision == "unknown"]
        if excluded:
            result.message += "\n\n安全提示：该食谱命中你的饮食限制，不应食用。"
            result.metadata["safety_review"] = "blocked"
        elif unknown:
            if "无法据此确认全部过敏风险" not in result.message:
                result.message += (
                    "\n\n安全提示：现有食材证据不足，无法确认是否满足你的饮食限制。"
                )
            result.metadata["safety_review"] = "unknown"
        else:
            result.metadata["safety_review"] = "passed"
        return {"result": result}
    passed = [item.name for item in review.recipes if item.decision == "passed"]
    if result.recipe is not None and result.recipe.name not in passed:
        result.recipe = None
    result.message = render_review_reply(review)
    result.sources = []  # Draft attributions may include excluded recipe recommendations.
    result.metadata["safety_review"] = "passed" if passed else "blocked"
    result.metadata["safe_recipe_names"] = passed
    result.metadata["recipe_reviews"] = [
        item.model_dump(mode="json", exclude={"evidence"}) for item in review.recipes
    ]
    if not passed:
        result.status = "degraded"
        result.error_code = "insufficient_safety_evidence"
    return {"result": result}
