"""Agent 图运行状态。

状态只保存计划、工具调用、观察、反思和最终回答所需的数据，避免把外部资源
或不可序列化对象放入 LangGraph 状态。
"""

from typing import Annotated, TypeAlias, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages

from safemeal.modules.conversation.contracts.conversation.models import (
    ConversationHistory,
    ConversationMessage,
)
from safemeal.agent.contracts.intent import IntentDecision
from safemeal.shared.types import JsonObject

from safemeal.modules.conversation.contracts.conversation.models import (
    AnswerSource,
    RouterInfo,
)
from safemeal.agent.runtime.tools.contracts.base import ToolResult

from safemeal.agent.contracts.decisions import Observation, ToolCall

MessageInput: TypeAlias = AnyMessage | ConversationMessage


# 类说明（数据契约类）：AgentInputState
# 作用：描述Agent 图输入状态的结构、类型及可校验字段。
class AgentInputState(TypedDict, total=False):
    # 字段说明：messages
    # 作用：按顺序组织的历史对话消息。
    # 类型：Annotated[list[MessageInput], add_messages]。
    messages: Annotated[list[MessageInput], add_messages]
    # 字段说明：agent_context
    # 作用：Agent 本轮执行共享的上下文对象。
    # 类型：JsonObject。
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
| `menu_execution_plan` | 复杂菜单的稳定配额目标 |
| `menu_task_progress` | 已完成、剩余、候选和已选菜品 |
"""


# 类说明（数据契约类）：AgentState
# 作用：描述Agent 完整图状态的结构、类型及可校验字段。
class AgentState(TypedDict, total=False):
    # 字段说明：intent
    # 作用：已识别的本轮请求意图。
    # 类型：IntentDecision | None。
    intent: IntentDecision | None
    # 字段说明：messages
    # 作用：按顺序组织的历史对话消息。
    # 类型：Annotated[list[MessageInput], add_messages]。
    messages: Annotated[list[MessageInput], add_messages]
    # 字段说明：agent_context
    # 作用：Agent 本轮执行共享的上下文对象。
    # 类型：JsonObject。
    agent_context: JsonObject
    # 字段说明：question
    # 作用：本轮用户消息或问题文本。
    # 类型：str。
    question: str
    # 字段说明：conversation_history
    # 作用：按顺序组织的历史对话消息。
    # 类型：ConversationHistory。
    conversation_history: ConversationHistory
    # 字段说明：pending_calls
    # 作用：已规划但尚未执行的工具调用集合。
    # 类型：list[ToolCall]。
    pending_calls: list[ToolCall]
    # 字段说明：tool_results
    # 作用：已完成工具调用返回的结果集合。
    # 类型：list[ToolResult]。
    tool_results: list[ToolResult]
    # 字段说明：observations
    # 作用：本轮已获得的工具观察集合。
    # 类型：list[Observation]。
    observations: list[Observation]
    # 字段说明：planning_rationale
    # 作用：规划或审核给出的理由说明。
    # 类型：str。
    planning_rationale: str
    # 字段说明：reflection_rationale
    # 作用：反思阶段对证据充分性的说明。
    # 类型：str。
    reflection_rationale: str
    # 字段说明：evidence_sufficient
    # 作用：现有证据是否足以完成任务。
    # 类型：bool。
    evidence_sufficient: bool
    # 字段说明：missing_information
    # 作用：当前任务尚缺少的信息集合。
    # 类型：list[str]。
    missing_information: list[str]
    # 字段说明：direct_answer
    # 作用：无需继续调用工具即可返回给用户的答复文本。
    # 类型：str。
    direct_answer: str
    # 字段说明：iteration
    # 作用：当前 Agent 循环次数。
    # 类型：int。
    iteration: int
    # 字段说明：max_iterations
    # 作用：Agent 循环最多执行次数。
    # 类型：int。
    max_iterations: int
    # 字段说明：route
    # 作用：HTTP 路由模板或业务路由标识。
    # 类型：str。
    route: str
    # 字段说明：router
    # 作用：HTTP 路由对象或回答路由说明。
    # 类型：RouterInfo。
    router: RouterInfo
    # 字段说明：sources
    # 作用：当前答案或上下文的证据来源集合。
    # 类型：list[AnswerSource]。
    sources: list[AnswerSource]
    # 字段说明：dietary_constraints
    # 作用：用户饮食约束数据，包含过敏、限制与偏好。
    # 类型：JsonObject。
    dietary_constraints: JsonObject
    # 字段说明：executed_call_signatures
    # 作用：已执行调用的签名集合，用于阻止相同参数的无效重复调用。
    # 类型：list[str]。
    executed_call_signatures: list[str]
    # 字段说明：tool_call_count
    # 作用：本轮累计工具调用次数。
    # 类型：int。
    tool_call_count: int
    # 字段说明：max_tool_calls
    # 作用：当前请求允许执行的工具调用总数。
    # 类型：int。
    max_tool_calls: int
    # 字段说明：max_model_tokens
    # 作用：当前请求模型调用的 Token 总量上限。
    # 类型：int。
    max_model_tokens: int
    # 字段说明：max_model_cost
    # 作用：当前请求模型调用的成本上限。
    # 类型：float。
    max_model_cost: float
    # 字段说明：budget_exhausted
    # 作用：本轮令牌、成本、工具次数或执行时间预算是否已耗尽。
    # 类型：bool。
    budget_exhausted: bool
    # 字段说明：loop_stop_reason
    # 作用：执行循环终止原因，用于解释预算、失败或任务完成等停止条件。
    # 类型：str。
    loop_stop_reason: str
    # 字段说明：menu_execution_plan
    # 作用：已编排的菜单执行计划，记录分类任务与候选获取步骤。
    # 类型：JsonObject。
    menu_execution_plan: JsonObject
    # 字段说明：menu_task_progress
    # 作用：菜单规划各配额的执行进度。
    # 类型：JsonObject。
    menu_task_progress: JsonObject
    # 字段说明：tool_trace
    # 作用：本轮已收集的工具调用轨迹。
    # 类型：list[JsonObject]。
    tool_trace: list[JsonObject]


# 类说明（业务或基础设施实现类）：AgentStateUpdate
# 作用：LangGraph 节点返回的局部状态更新。
class AgentStateUpdate(AgentState, total=False):
    """LangGraph 节点返回的局部状态更新。

    LangGraph 每个节点并不返回完整状态，而是返回需要合并进状态机的字段。
    单独定义这个类型，可以让 planner/execute/observe/reflect/respond 的返回值
    不再退化成 ``dict[str, object]``。
    """
