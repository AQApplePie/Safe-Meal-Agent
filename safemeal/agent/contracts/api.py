"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from safemeal.agent.contracts.context import AgentContext
from safemeal.modules.conversation.contracts.conversation.models import (
    AnswerSource,
)
from safemeal.agent.contracts.intent import IntentDecision
from safemeal.shared.types import JsonObject
from safemeal.modules.recipe.contracts.generated import GeneratedRecipe


# 类说明（数据契约类）：AgentProcessResponse
# 作用：Agent 内部处理响应。
class AgentProcessResponse(BaseModel):
    """Agent 内部处理响应。"""

    # 字段说明：status
    # 作用：HTTP 状态码或业务状态。
    # 类型：Literal['ok', 'degraded', 'error']。
    # 初始值：'ok'。
    # 取值说明：
    #   ok：操作正常。
    #   degraded：以降级能力提供服务。
    #   error：执行出错。
    status: Literal["ok", "degraded", "error"] = "ok"
    # 字段说明：message
    # 作用：本轮用户消息或问题文本。
    # 类型：str。
    message: str
    # 字段说明：route
    # 作用：HTTP 路由模板或业务路由标识。
    # 类型：Optional[str]。
    # 初始值：None。
    route: Optional[str] = None
    # 字段说明：route_logic
    # 作用：决定执行分支的路由函数。
    # 类型：Optional[str]。
    # 初始值：None。
    route_logic: Optional[str] = None
    # 字段说明：sources
    # 作用：当前答案或上下文的证据来源集合。
    # 类型：List[AnswerSource]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    sources: List[AnswerSource] = Field(default_factory=list)
    # 字段说明：metadata
    # 作用：文档、消息或证据的来源与辅助元数据。
    # 类型：JsonObject。
    # 配置：默认值工厂（每次创建独立对象）=dict。
    metadata: JsonObject = Field(default_factory=dict)
    # 字段说明：error_code
    # 作用：对外稳定的错误码。
    # 类型：Optional[str]。
    # 初始值：None。
    error_code: Optional[str] = None
    # 字段说明：recipe
    # 作用：当前菜谱或菜谱记录。
    # 类型：Optional[GeneratedRecipe]。
    # 初始值：None。
    recipe: Optional[GeneratedRecipe] = None
    # 字段说明：evidence
    # 作用：当前任务可使用的证据。
    # 类型：list[JsonObject]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    evidence: list[JsonObject] = Field(default_factory=list)
    # 字段说明：intent
    # 作用：已识别的本轮请求意图。
    # 类型：IntentDecision | None。
    # 初始值：None。
    intent: IntentDecision | None = None


# 类说明（数据契约类）：AgentResumeRequest
# 作用：描述Agent 审批恢复请求的结构、类型及可校验字段。
class AgentResumeRequest(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(extra="forbid")
    # 字段说明：session_id
    # 作用：聊天会话或图检查点线程标识。
    # 类型：str。
    # 配置：最小长度=1；最大长度=255。
    session_id: str = Field(min_length=1, max_length=255)
    # 字段说明：approved
    # 作用：用户是否明确同意执行当前待审批操作。
    # 类型：bool。
    approved: bool = Field(strict=True)
    # 字段说明：approval_id
    # 作用：绑定当前待审批操作的审批标识。
    # 类型：str。
    # 配置：最小长度=1；最大长度=255。
    approval_id: str = Field(min_length=1, max_length=255)
    # 字段说明：message_id
    # 作用：聊天消息标识。
    # 类型：int。
    # 配置：最小值（含）=1。
    message_id: int = Field(ge=1)


# 类说明（数据契约类）：AgentResumeResult
# 作用：描述Agent 审批恢复结果的结构、类型及可校验字段。
class AgentResumeResult(BaseModel):
    # 字段说明：response
    # 作用：底层客户端响应或最终业务响应。
    # 类型：AgentProcessResponse。
    response: AgentProcessResponse
    # 字段说明：message
    # 作用：本轮用户消息或问题文本。
    # 类型：str。
    # 初始值：''。
    message: str = ""
    # 字段说明：context
    # 作用：本轮执行上下文。
    # 类型：AgentContext。
    # 配置：默认值工厂（每次创建独立对象）=AgentContext。
    context: AgentContext = Field(default_factory=AgentContext)
