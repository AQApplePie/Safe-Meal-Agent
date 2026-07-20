"""聊天会话写入契约。

这些 DTO 只用于应用服务与持久化端口之间传递数据。HTTP 请求模型位于
``back.interfaces.http.models``，避免把客户端可控字段直接传给存储层。
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from SafeMealAgent.back.shared.types import JsonObject


ChatMessageType = Literal["user_query", "agent_response", "knowledge", "error"]


class ChatSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(..., min_length=1, max_length=255, description="Session UUID")
    title: str = Field(..., min_length=1, max_length=500, description="Session title")
    user_id: str = Field(
        ..., min_length=1, max_length=255, description="User identifier"
    )


class ChatSessionUpdate(BaseModel):
    """可变会话属性；会话所有者不能通过更新接口转移。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def require_change(self) -> "ChatSessionUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one session field must be provided")
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title cannot be null")
        if "is_active" in self.model_fields_set and self.is_active is None:
            raise ValueError("is_active cannot be null")
        return self


class ChatMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str = Field(..., min_length=1, max_length=255)
    message_type: ChatMessageType
    content: str = Field(..., min_length=1, max_length=100_000)
    message_metadata: Optional[JsonObject] = None
    order_index: int = Field(..., ge=1)
    client_request_id: Optional[str] = Field(default=None, min_length=1, max_length=255)
    reply_to_message_id: Optional[int] = Field(default=None, ge=1)
    turn_status: Optional[Literal["processing", "completed", "failed"]] = None


class ChatMessageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message_type: Optional[ChatMessageType] = None
    content: Optional[str] = Field(default=None, min_length=1, max_length=100_000)
    message_metadata: Optional[JsonObject] = None
    turn_status: Optional[Literal["processing", "completed", "failed"]] = None
