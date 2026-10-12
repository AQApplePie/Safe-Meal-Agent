"""调用 Agent 前分别解析用户偏好、过敏和饮食限制。"""

from safemeal.agent.workflow.streaming import emit_workflow_progress
from safemeal.agent.contracts.workflow.models import WorkflowState
from safemeal.agent.safety.dietary_safety_service import (
    DietarySafetyService,
    hard_constraints,
)


# 方法说明：resolve_constraints
# 作用：将本轮输入、历史与记忆合并为冻结的饮食执行要求。
# 入参：
#   state（WorkflowState）：聊天 Workflow 完整状态。
# 出参：WorkflowState；聊天 Workflow 完整状态。
async def resolve_constraints(state: WorkflowState) -> WorkflowState:
    await emit_workflow_progress("resolve_constraints", "正在整理偏好、过敏与本轮要求")
    context = state["context"].model_copy(deep=True)
    request = state["request"]
    requirements = (
        context.requirements.model_copy(deep=True)
        if request.resume_approved is not None and context.requirements is not None
        else DietarySafetyService().resolve_constraints(request.message, context)
    )
    context.requirements = requirements.model_copy(deep=True)
    context.dietary_constraints = hard_constraints(requirements).model_dump(mode="json")
    return {
        "context": context,
        "requirements": requirements,
    }
