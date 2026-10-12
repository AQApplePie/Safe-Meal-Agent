"""聊天会话写入契约。

这些 DTO 只用于应用服务与持久化端口之间传递数据。HTTP 请求模型位于
``safemeal.interfaces.http.models``，避免把客户端可控字段直接传给存储层。
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from safemeal.shared.types import JsonObject


ChatMessageType = Literal["user_query", "agent_response", "knowledge", "error"]


# 类说明（数据契约类）：ChatSessionCreate
# 作用：描述聊天会话创建命令的结构、类型及可校验字段。
class ChatSessionCreate(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'；是否禁止构造后修改字段=True。
    model_config = ConfigDict(extra="forbid", frozen=True)

    # 字段说明：id
    # 作用：聊天会话的 UUID 标识。
    # 类型：str。
    # 配置：最小长度=1；最大长度=255。
    id: str = Field(..., min_length=1, max_length=255, description="Session UUID")
    # 字段说明：title
    # 作用：聊天会话标题，用于列表展示。
    # 类型：str。
    # 配置：最小长度=1；最大长度=500。
    title: str = Field(..., min_length=1, max_length=500, description="Session title")
    # 字段说明：user_id
    # 作用：会话所属用户的持久化标识。
    # 类型：str。
    # 配置：最小长度=1；最大长度=255。
    user_id: str = Field(
        ..., min_length=1, max_length=255, description="User identifier"
    )


# 类说明（数据契约类）：ChatSessionUpdate
# 作用：可变会话属性；会话所有者不能通过更新接口转移。
class ChatSessionUpdate(BaseModel):
    """可变会话属性；会话所有者不能通过更新接口转移。"""

    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'；是否禁止构造后修改字段=True。
    model_config = ConfigDict(extra="forbid", frozen=True)

    # 字段说明：title
    # 作用：会话、文档或菜谱标题。
    # 类型：Optional[str]。
    # 配置：默认值=None；最小长度=1；最大长度=500。
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    # 字段说明：is_active
    # 作用：该记录或约束是否处于生效状态。
    # 类型：Optional[bool]。
    # 初始值：None。
    is_active: Optional[bool] = None

    # 方法说明：require_change
    # 作用：校验会话更新至少包含一个可修改字段，且显式字段不能为无效空值。
    # 入参：
    #   无显式入参。
    # 出参：'ChatSessionUpdate'；聊天会话更新命令。
    @model_validator(mode="after")
    def require_change(self) -> "ChatSessionUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one session field must be provided")
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title cannot be null")
        if "is_active" in self.model_fields_set and self.is_active is None:
            raise ValueError("is_active cannot be null")
        return self


# 类说明（数据契约类）：ChatMessageCreate
# 作用：描述聊天消息创建命令的结构、类型及可校验字段。
class ChatMessageCreate(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'；是否禁止构造后修改字段=True。
    model_config = ConfigDict(extra="forbid", frozen=True)

    # 字段说明：session_id
    # 作用：聊天会话或图检查点线程标识。
    # 类型：str。
    # 配置：最小长度=1；最大长度=255。
    session_id: str = Field(..., min_length=1, max_length=255)
    # 字段说明：message_type
    # 作用：消息在对话流程中的业务类型。
    # 类型：ChatMessageType。
    # 取值说明：
    #   user_query：用户查询内容。
    #   agent_response：Agent 生成的回复。
    #   knowledge：查询饮食知识。
    #   error：执行出错。
    message_type: ChatMessageType
    # 字段说明：content
    # 作用：当前文件、消息或证据的正文内容。
    # 类型：str。
    # 配置：最小长度=1；最大长度=100000。
    content: str = Field(..., min_length=1, max_length=100_000)
    # 字段说明：message_metadata
    # 作用：消息附属元数据，保存执行或来源信息。
    # 类型：Optional[JsonObject]。
    # 初始值：None。
    message_metadata: Optional[JsonObject] = None
    # 字段说明：order_index
    # 作用：对象在当前列表或会话内的顺序位置。
    # 类型：int。
    # 配置：最小值（含）=1。
    order_index: int = Field(..., ge=1)
    # 字段说明：client_request_id
    # 作用：客户端提供的请求标识，用于识别同一请求并支持幂等处理。
    # 类型：Optional[str]。
    # 配置：默认值=None；最小长度=1；最大长度=255。
    client_request_id: Optional[str] = Field(default=None, min_length=1, max_length=255)
    # 字段说明：reply_to_message_id
    # 作用：被当前回复关联的原始消息标识。
    # 类型：Optional[int]。
    # 配置：默认值=None；最小值（含）=1。
    reply_to_message_id: Optional[int] = Field(default=None, ge=1)
    # 字段说明：turn_status
    # 作用：本轮对话或执行的最终状态。
    # 类型：Optional[Literal['processing', 'completed', 'failed']]。
    # 初始值：None。
    # 取值说明：
    #   processing：正在处理。
    #   completed：处理完成。
    #   failed：处理失败。
    turn_status: Optional[Literal["processing", "completed", "failed"]] = None


# 类说明（数据契约类）：ChatMessageUpdate
# 作用：描述聊天消息更新命令的结构、类型及可校验字段。
class ChatMessageUpdate(BaseModel):
    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    # 配置：额外字段策略（forbid 禁止，ignore 忽略）='forbid'；是否禁止构造后修改字段=True。
    model_config = ConfigDict(extra="forbid", frozen=True)

    # 字段说明：message_type
    # 作用：消息在对话流程中的业务类型。
    # 类型：Optional[ChatMessageType]。
    # 初始值：None。
    # 取值说明：
    #   user_query：用户查询内容。
    #   agent_response：Agent 生成的回复。
    #   knowledge：查询饮食知识。
    #   error：执行出错。
    message_type: Optional[ChatMessageType] = None
    # 字段说明：content
    # 作用：当前文件、消息或证据的正文内容。
    # 类型：Optional[str]。
    # 配置：默认值=None；最小长度=1；最大长度=100000。
    content: Optional[str] = Field(default=None, min_length=1, max_length=100_000)
    # 字段说明：message_metadata
    # 作用：消息附属元数据，保存执行或来源信息。
    # 类型：Optional[JsonObject]。
    # 初始值：None。
    message_metadata: Optional[JsonObject] = None
    # 字段说明：turn_status
    # 作用：本轮对话或执行的最终状态。
    # 类型：Optional[Literal['processing', 'completed', 'failed']]。
    # 初始值：None。
    # 取值说明：
    #   processing：正在处理。
    #   completed：处理完成。
    #   failed：处理失败。
    turn_status: Optional[Literal["processing", "completed", "failed"]] = None
