"""Chat workflow wiring only. Node implementations live in nodes/."""

from langgraph.graph import StateGraph, START, END
from safemeal.application.contracts.workflow.models import WorkflowState
from safemeal.application.ports.agent import AgentInvoker
from safemeal.application.workflow.context.builder import AgentContextBuilder
from safemeal.application.service.memory.user_memory_service import UserMemoryService
from .nodes.resume_agent import ResumeAgentNode
from .nodes.load_memory import LoadMemoryNode
from .nodes.constraints import resolve_constraints
from .nodes.intent import IdentifyIntentNode
from safemeal.application.ports.llm.intent_classifier import IntentClassifier
from .nodes.invoke_agent import InvokeAgentNode
from .nodes.direct_reply import direct_reply
from .nodes.safety import check_final_safety
from .nodes.save_memory import SaveMemoryNode
from .routing import after_intent


def build_chat_workflow(
    *,
    agent: AgentInvoker,
    context_builder: AgentContextBuilder,
    memory_service: UserMemoryService,
    intent_classifier: IntentClassifier | None = None,
):
    graph = StateGraph(WorkflowState)
    graph.add_node("load_memory", LoadMemoryNode(context_builder))
    graph.add_node("resolve_constraints", resolve_constraints)
    graph.add_node("identify_intent", IdentifyIntentNode(intent_classifier))
    graph.add_node("invoke_agent", InvokeAgentNode(agent))
    graph.add_node("direct_reply", direct_reply)
    graph.add_node("final_safety", check_final_safety)
    graph.add_node("save_memory", SaveMemoryNode(memory_service))
    graph.add_edge(START, "load_memory")
    graph.add_edge("load_memory", "resolve_constraints")
    graph.add_edge("resolve_constraints", "identify_intent")
    graph.add_conditional_edges(
        "identify_intent",
        after_intent,
        {"invoke_agent": "invoke_agent", "direct_reply": "direct_reply"},
    )
    graph.add_edge("invoke_agent", "final_safety")
    graph.add_edge("direct_reply", "final_safety")
    graph.add_edge("final_safety", "save_memory")
    graph.add_edge("save_memory", END)
    return graph.compile()


def build_resume_workflow(*, agent):
    """Resume checkpoints through the same constraint and publication gates."""
    graph = StateGraph(WorkflowState)
    graph.add_node("resume_agent", ResumeAgentNode(agent))
    graph.add_node("resolve_constraints", resolve_constraints)
    graph.add_node("identify_intent", IdentifyIntentNode())
    graph.add_node("final_safety", check_final_safety)
    graph.add_edge(START, "resume_agent")
    graph.add_edge("resume_agent", "resolve_constraints")
    graph.add_edge("resolve_constraints", "identify_intent")
    graph.add_edge("identify_intent", "final_safety")
    graph.add_edge("final_safety", END)
    return graph.compile()
