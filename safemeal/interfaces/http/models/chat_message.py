"""实现 HTTP 接口层的请求与响应适配。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from safemeal.shared.types import JsonObject


MessageType = Literal["user_query", "agent_response", "knowledge", "error"]


# 类说明（数据契约类）：ChatMessageResponse
# 作用：描述聊天消息 HTTP 响应的结构、类型及可校验字段。
class ChatMessageResponse(BaseModel):

    # 字段说明：model_config
    # 作用：模型构造与校验配置，控制可变性、额外字段及环境变量读取方式。
    model_config = ConfigDict(from_attributes=True)

    # 字段说明：id
    # 作用：该业务记录的唯一标识，SQL 模型中通常对应主键。
    # 类型：int。
    id: int
    # 字段说明：session_id
    # 作用：聊天会话或图检查点线程标识。
    # 类型：str。
    session_id: str
    # 字段说明：message_type
    # 作用：消息在对话流程中的业务类型。
    # 类型：MessageType。
    # 取值说明：
    #   user_query：用户查询内容。
    #   agent_response：Agent 生成的回复。
    #   knowledge：查询饮食知识。
    #   error：执行出错。
    message_type: MessageType
    # 字段说明：content
    # 作用：当前文件、消息或证据的正文内容。
    # 类型：str。
    content: str
    # 字段说明：message_metadata
    # 作用：消息附属元数据，保存执行或来源信息。
    # 类型：Optional[JsonObject]。
    # 初始值：None。
    message_metadata: Optional[JsonObject] = None
    # 字段说明：order_index
    # 作用：对象在当前列表或会话内的顺序位置。
    # 类型：int。
    order_index: int
    # 字段说明：client_request_id
    # 作用：客户端提供的请求标识，用于识别同一请求并支持幂等处理。
    # 类型：Optional[str]。
    # 初始值：None。
    client_request_id: Optional[str] = None
    # 字段说明：reply_to_message_id
    # 作用：被当前回复关联的原始消息标识。
    # 类型：Optional[int]。
    # 初始值：None。
    reply_to_message_id: Optional[int] = None
    # 字段说明：turn_status
    # 作用：本轮对话或执行的最终状态。
    # 类型：Optional[Literal['processing', 'completed', 'failed']]。
    # 初始值：None。
    # 取值说明：
    #   processing：正在处理。
    #   completed：处理完成。
    #   failed：处理失败。
    turn_status: Optional[Literal["processing", "completed", "failed"]] = None
    # 字段说明：created_at
    # 作用：记录创建时间，用于排序和审计。
    # 类型：datetime。
    created_at: datetime
    # 字段说明：updated_at
    # 作用：记录最后更新时间。
    # 类型：Optional[datetime]。
    # 初始值：None。
    updated_at: Optional[datetime] = None

    # 方法说明：normalize_utc
    # 作用：将日期时间归一化为 UTC，统一时间比较与存储语义。
    # 入参：
    #   value（Optional[datetime]）：当前待转换或校验的值。
    # 出参：Optional[datetime]；日期时间或 None。
    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def normalize_utc(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


__all__ = [
    "ChatMessageResponse",
    "MessageType",
]
