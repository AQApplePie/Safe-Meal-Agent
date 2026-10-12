"""实现聊天工作流中的对应职责。"""

from safemeal.agent.contracts.workflow.models import WorkflowRequest
from safemeal.agent.contracts.api import AgentProcessResponse
from safemeal.agent.runtime.observability import observe_request
from safemeal.agent.workflow.streaming import suppress_answer_stream


# 类说明（业务或基础设施实现类）：ChatWorkflow
# 作用：实现聊天 Workflow 执行入口，封装该组件的业务处理与依赖协作。
class ChatWorkflow:
    # 方法说明：__init__
    # 作用：初始化聊天 Workflow 执行入口，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   graph（由调用契约决定）：图执行对象或图数据库封装。
    #   resume_graph（由调用契约决定）：已编译的审批恢复 Workflow；默认值为 None。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, graph, resume_graph=None):
        # 实例属性说明：graph
        # 作用：图执行对象或图数据库封装。
        self.graph = graph
        # 实例属性说明：resume_graph
        # 作用：已编译的审批恢复 Workflow。
        self.resume_graph = resume_graph

    # 方法说明：run
    # 作用：执行聊天 Workflow 执行入口的业务处理流程。
    # 入参：
    #   request（WorkflowRequest）：聊天 Workflow 输入请求。
    # 出参：AgentProcessResponse；Agent 内部处理响应。
    async def run(self, request: WorkflowRequest) -> AgentProcessResponse:
        with observe_request() as observation, suppress_answer_stream():
            state = await self.graph.ainvoke({"request": request})
        result = state["result"]
        result.metadata["agent_status"] = result.status
        result.metadata["observability"] = observation.snapshot()

        return result.model_copy(update={"evidence": []})

    # 方法说明：resume
    # 作用：从持久化中断状态恢复当前审批任务并整理执行结果。
    # 入参：
    #   session_id（str）：聊天会话或图检查点线程标识。
    #   approved（bool）：用户是否明确同意执行当前待审批操作。
    # 出参：AgentProcessResponse；Agent 内部处理响应。
    async def resume(self, session_id: str, *, approved: bool) -> AgentProcessResponse:
        if self.resume_graph is None:
            raise RuntimeError("This workflow has no resumable Agent")
        with observe_request() as observation, suppress_answer_stream():
            state = await self.resume_graph.ainvoke(
                {
                    "request": WorkflowRequest(
                        message="",
                        user_id="internal_user",
                        session_id=session_id,
                        use_user_memory=False,
                        resume_approved=approved,
                    )
                }
            )
        result = state["result"]
        result.metadata["agent_status"] = result.status
        result.metadata["observability"] = observation.snapshot()

        return result.model_copy(update={"evidence": []})
