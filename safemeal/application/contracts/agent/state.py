"""Agent 图运行状态。

状态只保存计划、工具调用、观察、反思和最终回答所需的数据，避免把外部资源
或不可序列化对象放入 LangGraph 状态。
"""

from typing import Annotated, TypeAlias, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

from safemeal.application.contracts.conversation.models import (
    ConversationHistory,
    ConversationMessage,
)
from safemeal.shared.types import JsonObject

from safemeal.application.contracts.conversation.models import AnswerSource, RouterInfo
from safemeal.application.contracts.tools.base import ToolResult

from safemeal.application.contracts.agent.decisions import Observation, ToolCall

MessageInput: TypeAlias = AnyMessage | ConversationMessage


class AgentInputState(TypedDict, total=False):
    messages: Annotated[list[MessageInput], add_messages]
    agent_context: JsonObject


"""
| 字段 | 作用 |
|---|---|
| `messages` | 当前请求及历史消息 |
| `agent_context` | 本轮 Agent 统一输入上下文 |
| `question` | 当前用户问题 |
| `conversation_history` | 排除当前问题后的历史 |
| `pending_calls` | 下一批待执行工具 |
| `tool_results` | 工具刚刚返回的原始结果 |
| `observations` | 已标准化的全部观察记录 |
| `planning_rationale` | Planner 选择方案的理由 |
| `reflection_rationale` | Reflection 的判断理由 |
| `evidence_sufficient` | 当前证据是否充分 |
| `missing_information` | 仍缺少的信息 |
| `iteration` | 已执行工具批次数 |
| `max_iterations` | 最大工具迭代次数 |
| `route` | 下一步行为 |
| `sources` | 数据来源 |
| `dietary_constraints` | 忌口/过敏等饮食安全约束 |
"""


class AgentState(TypedDict, total=False):
    messages: Annotated[list[MessageInput], add_messages]
    agent_context: JsonObject
    question: str
    conversation_history: ConversationHistory
    pending_calls: list[ToolCall]
    tool_results: list[ToolResult]
    observations: list[Observation]
    planning_rationale: str
    reflection_rationale: str
    evidence_sufficient: bool
    missing_information: list[str]
    direct_answer: str
    iteration: int
    max_iterations: int
    route: str
    router: RouterInfo
    sources: list[AnswerSource]
    dietary_constraints: JsonObject
    safety_gate_blocked: bool
    executed_call_signatures: list[str]
    tool_call_count: int
    max_tool_calls: int
    max_model_tokens: int
    max_model_cost: float
    budget_exhausted: bool
    loop_stop_reason: str
    human_approved: bool
    approval_required: bool


class AgentStateUpdate(AgentState, total=False):
    """LangGraph 节点返回的局部状态更新。

    LangGraph 每个节点并不返回完整状态，而是返回需要合并进状态机的字段。
    单独定义这个类型，可以让 planner/execute/observe/reflect/respond 的返回值
    不再退化成 ``dict[str, object]``。
    """
