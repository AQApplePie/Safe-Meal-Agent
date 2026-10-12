"""实现聊天工作流中的对应职责。"""

from safemeal.agent.workflow.streaming import emit_workflow_progress
from safemeal.agent.contracts.workflow.models import WorkflowState
from safemeal.agent.contracts.ports import AgentInvoker
from safemeal.agent.workflow.streaming import suppress_answer_stream


# 类说明（业务或基础设施实现类）：InvokeAgentNode
# 作用：实现Workflow Agent 执行节点，封装该组件的业务处理与依赖协作。
class InvokeAgentNode:
    # 方法说明：__init__
    # 作用：初始化Workflow Agent 执行节点，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   agent（AgentInvoker）：已装配的 Agent 执行对象。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, agent: AgentInvoker):
        # 实例属性说明：agent
        # 作用：已装配的 Agent 执行对象。
        self.agent = agent

    # 方法说明：__call__
    # 作用：执行Workflow Agent 执行节点，按当前图状态返回节点更新。
    # 入参：
    #   state（WorkflowState）：聊天 Workflow 完整状态。
    # 出参：WorkflowState；聊天 Workflow 完整状态。
    async def __call__(self, state: WorkflowState) -> WorkflowState:
        await emit_workflow_progress("invoke_agent", "正在查找和整理食谱")
        request = state["request"]

        with suppress_answer_stream():
            result = await self.agent.process(
                request.message,
                request.session_id,
                context=state["context"].model_copy(deep=True),
            )
        result = result.model_copy(deep=True)
        for key in (
            "request_understanding_backend",
            "request_understanding_confidence",
            "understanding_status",
            "request_tasks",
            "context_needs",
            "fallback_used",
            "loaded_context_types",
        ):
            value = state["context"].context_metadata.get(key)
            if value is not None:
                result.metadata[key] = value
        return {"result": result}
