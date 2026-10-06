"""按照 Agent 执行前冻结的要求复核结构化菜谱证据。"""

from safemeal.application.streaming import emit_workflow_progress
from safemeal.application.contracts.workflow.models import WorkflowState
from safemeal.application.contracts.agent.decisions import Observation
from safemeal.application.service.dietary_safety.dietary_safety_service import (
    DietarySafetyService,
)
from safemeal.application.workflow.review_reply import (
    render_conversational_review_reply,
)
from safemeal.application.service.recipes.menu_output import render_menu_plan
from safemeal.application.contracts.agent.menu_planning import (
    MenuExecutionPlan,
    MenuTaskProgress,
)
from safemeal.application.service.recipes.menu_coverage import (
    calculate_menu_coverage,
)

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
    # 菜谱卡片也是发布内容，只能补充已有生成证据，不能单独伪造成功结果。
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
    if result.intent is not None and result.intent.kind == "menu_planning":
        # 工具会过采样候选；这里只发布已占用配额且通过最终安全复核的菜品。
        selected_progress = result.metadata.get("menu_task_progress")
        execution_plan = result.metadata.get("menu_execution_plan")
        passed_names = {
            item.name for item in review.recipes if item.decision == "passed"
        }
        selected_names = {
            str(item.get("name"))
            for item in (selected_progress or {}).get("selected_recipes", [])
            if isinstance(item, dict) and item.get("name")
        }
        publishable = selected_names & passed_names
        validated_plan = MenuExecutionPlan.model_validate(execution_plan or {})
        validated_progress = MenuTaskProgress.model_validate(selected_progress or {})
        post_safety_fulfilled, post_safety_remaining, post_safety_complete = (
            calculate_menu_coverage(
                validated_plan,
                validated_progress.selected_recipes,
                allowed_names=publishable,
            )
        )
        result.metadata["post_safety_coverage"] = {
            "fulfilled": post_safety_fulfilled,
            "remaining": post_safety_remaining,
            "complete": post_safety_complete,
        }
        result.metadata["safe_recipe_names"] = sorted(publishable)
        result.metadata["recipe_reviews"] = [
            item.model_dump(mode="json", exclude={"evidence"})
            for item in review.recipes
            if item.name in selected_names
        ]
        if isinstance(execution_plan, dict) and isinstance(selected_progress, dict):
            result.message = render_menu_plan(
                execution_plan,
                selected_progress,
                allowed_names=publishable,
            )
        result.sources = []
        all_selected_safe = bool(selected_names) and publishable == selected_names
        result.metadata["safety_review"] = "passed" if all_selected_safe else "blocked"
        if not all_selected_safe:
            result.status = "degraded"
            result.error_code = "insufficient_safety_evidence"
        return {"result": result}
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
    frame = state.get("request_frame") or state["context"].request_frame
    result.message = render_conversational_review_reply(
        review,
        max_recommendations=(frame.recommendation_count if frame is not None else None),
    )
    # 草稿来源可能包含已排除候选，发布结果不沿用未经复核的来源。
    result.sources = []
    result.metadata["safety_review"] = "passed" if passed else "blocked"
    result.metadata["safe_recipe_names"] = passed
    result.metadata["recipe_reviews"] = [
        item.model_dump(mode="json", exclude={"evidence"}) for item in review.recipes
    ]
    completion = result.metadata.get("recommendation_completion")
    if isinstance(completion, dict) and not completion.get("complete", True):
        result.message += (
            f"\n\n说明：你请求了 {completion.get('requested')} 道，目前可核验的结果"
            f"只有 {completion.get('fulfilled')} 道，因此这是部分结果。"
        )
    if not passed:
        result.status = "degraded"
        result.error_code = "insufficient_safety_evidence"
    return {"result": result}
