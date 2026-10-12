"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations
from dataclasses import dataclass


from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from safemeal.modules.conversation.contracts.conversation.models import AnswerSource
from safemeal.shared.types import JsonObject
from safemeal.modules.recipe.contracts.generated import GeneratedRecipe


# 类说明（数据契约类）：ChatRequest
# 作用：用户聊天请求。
class ChatRequest(BaseModel):
    """用户聊天请求。"""

    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'。
    model_config = ConfigDict(extra="forbid")

    # 字段说明：message
    # 作用：本轮用户消息或问题文本。
    # 类型：str。
    # 配置：最小长度=1；最大长度=5000。
    message: str = Field(..., min_length=1, max_length=5000)
    # 字段说明：session_id
    # 作用：聊天会话或图检查点线程标识。
    # 类型：Optional[str]。
    # 配置：默认值=None；最小长度=1；最大长度=255。
    session_id: Optional[str] = Field(default=None, min_length=1, max_length=255)
    # 字段说明：request_id
    # 作用：客户端生成的幂等请求 ID；同一会话内必须唯一。
    # 类型：Optional[str]。
    # 配置：默认值=None；最小长度=1；最大长度=255。
    request_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="客户端生成的幂等请求 ID；同一会话内必须唯一。",
    )

    # 字段说明：user_id
    # 作用：经身份绑定后的持久化用户标识。
    # 类型：Optional[str]。
    # 配置：默认值=None；最小长度=1；最大长度=255。
    user_id: Optional[str] = Field(default=None, min_length=1, max_length=255)


# 类说明（数据契约类）：ChatResponse
# 作用：用户聊天响应。
class ChatResponse(BaseModel):
    """用户聊天响应。"""

    # 字段说明：message
    # 作用：本轮用户消息或问题文本。
    # 类型：str。
    message: str
    # 字段说明：session_id
    # 作用：聊天会话或图检查点线程标识。
    # 类型：str。
    session_id: str
    # 字段说明：message_id
    # 作用：聊天消息标识。
    # 类型：str。
    message_id: str
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
    # 字段说明：recipe
    # 作用：当前菜谱或菜谱记录。
    # 类型：Optional[GeneratedRecipe]。
    # 初始值：None。
    recipe: Optional[GeneratedRecipe] = None
    # 字段说明：timestamp
    # 作用：响应生成时间，默认使用 UTC 当前时间。
    # 类型：datetime。
    # 配置：默认值工厂（每次创建独立对象）=lambda: datetime.now(timezone.utc)。
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# 类说明（数据契约类）：ChatTurnStart
# 作用：描述聊天轮次启动结果的结构、类型及可校验字段。
@dataclass(frozen=True)
class ChatTurnStart:
    # 字段说明：session_id
    # 作用：聊天会话或图检查点线程标识。
    # 类型：str。
    session_id: str
    # 字段说明：user_message_id
    # 作用：本轮用户消息标识。
    # 类型：int。
    user_message_id: int
    # 字段说明：response_order_index
    # 作用：助手响应在会话中的顺序号。
    # 类型：int。
    response_order_index: int
