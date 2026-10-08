"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations
from dataclasses import dataclass


from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from safemeal.modules.conversation.contracts.conversation.models import AnswerSource
from safemeal.shared.types import JsonObject
from safemeal.modules.recipe.contracts.generated import GeneratedRecipe


class ChatRequest(BaseModel):
    """用户聊天请求。"""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1, max_length=5000)
    session_id: Optional[str] = Field(default=None, min_length=1, max_length=255)
    request_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="客户端生成的幂等请求 ID；同一会话内必须唯一。",
    )


    user_id: Optional[str] = Field(default=None, min_length=1, max_length=255)


class ChatResponse(BaseModel):
    """用户聊天响应。"""

    message: str
    session_id: str
    message_id: str
    route: Optional[str] = None
    route_logic: Optional[str] = None
    sources: List[AnswerSource] = Field(default_factory=list)
    metadata: JsonObject = Field(default_factory=dict)
    recipe: Optional[GeneratedRecipe] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class ChatTurnStart:
    session_id: str
    user_message_id: int
    response_order_index: int
