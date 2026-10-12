"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations
from dataclasses import dataclass
from safemeal.shared.types import JsonObject
from safemeal.modules.dietary.contracts.requirements import (
    DietaryRequirements,
)

from typing import TypedDict
from pydantic import BaseModel, Field
from safemeal.agent.contracts.api import AgentProcessResponse
from safemeal.agent.contracts.context import AgentContext
from safemeal.modules.conversation.contracts.conversation.models import (
    ConversationHistory,
)
from safemeal.shared.contracts.request_frame import RequestFrame


# 类说明（数据契约类）：WorkflowRequest
# 作用：描述聊天 Workflow 输入请求的结构、类型及可校验字段。
class WorkflowRequest(BaseModel):
    # 字段说明：message
    # 作用：本轮用户消息或问题文本。
    # 类型：str。
    message: str
    # 字段说明：user_id
    # 作用：经身份绑定后的持久化用户标识。
    # 类型：str。
    user_id: str
    # 字段说明：session_id
    # 作用：聊天会话或图检查点线程标识。
    # 类型：str。
    session_id: str
    # 字段说明：history
    # 作用：已加载的近期对话上下文。
    # 类型：ConversationHistory。
    # 配置：默认值工厂（每次创建独立对象）=list。
    history: ConversationHistory = Field(default_factory=list)
    # 字段说明：source_message_id
    # 作用：记忆或结果对应的来源消息标识。
    # 类型：str | None。
    # 初始值：None。
    source_message_id: str | None = None
    # 字段说明：context
    # 作用：本轮执行上下文。
    # 类型：AgentContext | None。
    # 初始值：None。
    context: AgentContext | None = None
    # 字段说明：use_user_memory
    # 作用：是否为本轮加载并使用长期记忆。
    # 类型：bool。
    # 初始值：True。
    use_user_memory: bool = True
    # 字段说明：resume_approved
    # 作用：本轮是否已取得继续执行的审批许可。
    # 类型：bool | None。
    # 初始值：None。
    resume_approved: bool | None = None


# 类说明（数据契约类）：WorkflowState
# 作用：描述聊天 Workflow 完整状态的结构、类型及可校验字段。
class WorkflowState(TypedDict, total=False):
    # 字段说明：request
    # 作用：HTTP 请求或应用层请求契约。
    # 类型：WorkflowRequest。
    request: WorkflowRequest
    # 字段说明：context
    # 作用：本轮执行上下文。
    # 类型：AgentContext。
    context: AgentContext
    # 字段说明：result
    # 作用：当前已获得的操作或工具结果。
    # 类型：AgentProcessResponse。
    result: AgentProcessResponse
    # 字段说明：requirements
    # 作用：本轮冻结的饮食或菜单执行要求。
    # 类型：DietaryRequirements。
    requirements: DietaryRequirements
    # 字段说明：request_frame
    # 作用：已归一化的请求语义框架。
    # 类型：RequestFrame。
    request_frame: RequestFrame
    # 字段说明：recent_history
    # 作用：近期浏览或对话历史记录。
    # 类型：ConversationHistory。
    recent_history: ConversationHistory
    # 字段说明：active_menu
    # 作用：本轮已有的结构化活动菜单。
    # 类型：JsonObject | None。
    active_menu: JsonObject | None


# 类说明（数据契约类）：ConversationContextResult
# 作用：描述历史对话上下文结果的结构、类型及可校验字段。
@dataclass(frozen=True)
class ConversationContextResult:
    # 字段说明：history
    # 作用：已加载的近期对话上下文。
    # 类型：ConversationHistory。
    history: ConversationHistory
    # 字段说明：episodic_memories
    # 作用：已加载的近期任务片段记忆。
    # 类型：list[JsonObject]。
    episodic_memories: list[JsonObject]
    # 字段说明：estimated_tokens
    # 作用：上下文预计占用的令牌数量，供预算裁剪使用。
    # 类型：int。
    estimated_tokens: int
    # 字段说明：summarized_messages
    # 作用：已被历史摘要覆盖的消息数量。
    # 类型：int。
    summarized_messages: int
