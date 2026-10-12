from safemeal.agent.workflow.streaming import emit_workflow_progress
from safemeal.agent.contracts.workflow.models import (
    WorkflowState,
    WorkflowRequest,
)
from safemeal.agent.contracts.ports import ResumableAgent
from safemeal.agent.workflow.streaming import suppress_answer_stream


# 类说明（业务或基础设施实现类）：ResumeAgentNode
# 作用：实现Workflow 审批恢复节点，封装该组件的业务处理与依赖协作。
class ResumeAgentNode:
    # 方法说明：__init__
    # 作用：初始化Workflow 审批恢复节点，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   agent（ResumableAgent）：已装配的 Agent 执行对象。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, agent: ResumableAgent):
        # 实例属性说明：agent
        # 作用：已装配的 Agent 执行对象。
        self.agent = agent

    # 方法说明：__call__
    # 作用：执行Workflow 审批恢复节点，按当前图状态返回节点更新。
    # 入参：
    #   state（WorkflowState）：聊天 Workflow 完整状态。
    # 出参：WorkflowState；聊天 Workflow 完整状态。
    async def __call__(self, state: WorkflowState) -> WorkflowState:
        await emit_workflow_progress("resume_agent", "正在恢复已确认的操作")
        request = state["request"]
        with suppress_answer_stream():
            resumed = await self.agent.resume(
                request.session_id, approved=bool(request.resume_approved)
            )
        return {
            "result": resumed.response,
            "context": resumed.context,
            "request": WorkflowRequest(
                message=resumed.message,
                session_id=request.session_id,
                user_id=str(
                    resumed.context.context_metadata.get("user_id") or "internal_user"
                ),
                context=resumed.context,
                use_user_memory=False,
                resume_approved=request.resume_approved,
            ),
        }
