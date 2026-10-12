"""实现聊天工作流中的对应职责。"""

from langgraph.graph import StateGraph, START, END
from safemeal.agent.contracts.workflow.models import WorkflowState
from safemeal.agent.contracts.ports import AgentInvoker
from safemeal.agent.workflow.context.builder import AgentContextBuilder
from safemeal.modules.conversation.application.memory.user_memory_service import (
    UserMemoryService,
)
from .nodes.resume_agent import ResumeAgentNode
from .nodes.prepare_context import PrepareContextNode
from .nodes.understand_request import UnderstandRequestNode
from safemeal.agent.understanding.port import RequestUnderstandingGateway
from .nodes.constraints import resolve_constraints
from .nodes.invoke_agent import InvokeAgentNode
from .nodes.safety import check_final_safety
from .nodes.save_memory import SaveMemoryNode


# 方法说明：build_chat_workflow
# 作用：编译请求理解、上下文准备、执行、安全复核和记忆保存流程。
# 入参：
#   agent（AgentInvoker）：已装配的 Agent 执行对象。
#   context_builder（AgentContextBuilder）：Agent 上下文构建器。
#   memory_service（UserMemoryService）：长期记忆业务服务。
#   request_understanding_gateway（RequestUnderstandingGateway |
# None）：把文本转换为请求语义框架的能力；默认值为 None。
# request_understanding_confidence_threshold（float）：请求理解结果允许进入执行流程的最低置信度；默认值为
# 0.7。
# 出参：按实现返回；已编译的 LangGraph 可执行图。
def build_chat_workflow(
    *,
    agent: AgentInvoker,
    context_builder: AgentContextBuilder,
    memory_service: UserMemoryService,
    request_understanding_gateway: RequestUnderstandingGateway | None = None,
    request_understanding_confidence_threshold: float = 0.7,
):
    graph = StateGraph(WorkflowState)
    graph.add_node("prepare_context", PrepareContextNode(context_builder))
    graph.add_node(
        "understand_request",
        UnderstandRequestNode(
            request_understanding_gateway,
            context_builder,
            confidence_threshold=request_understanding_confidence_threshold,
        ),
    )
    graph.add_node("resolve_constraints", resolve_constraints)
    graph.add_node("invoke_agent", InvokeAgentNode(agent))
    graph.add_node("final_safety", check_final_safety)
    graph.add_node("save_memory", SaveMemoryNode(memory_service))
    graph.add_edge(START, "understand_request")
    graph.add_edge("understand_request", "prepare_context")
    graph.add_edge("prepare_context", "resolve_constraints")
    graph.add_edge("resolve_constraints", "invoke_agent")
    graph.add_edge("invoke_agent", "final_safety")
    graph.add_edge("final_safety", "save_memory")
    graph.add_edge("save_memory", END)
    return graph.compile()


# 方法说明：build_resume_workflow
# 作用：编译从检查点恢复 Agent 并重新安全复核的流程。
# 入参：
#   agent（由调用契约决定）：已装配的 Agent 执行对象。
# 出参：按实现返回；已编译的 LangGraph 可执行图。
def build_resume_workflow(*, agent):
    graph = StateGraph(WorkflowState)
    graph.add_node("resume_agent", ResumeAgentNode(agent))
    graph.add_node("resolve_constraints", resolve_constraints)
    graph.add_node("final_safety", check_final_safety)
    graph.add_edge(START, "resume_agent")
    graph.add_edge("resume_agent", "resolve_constraints")
    graph.add_edge("resolve_constraints", "final_safety")
    graph.add_edge("final_safety", END)
    return graph.compile()
