"""Chat-turn application contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from safemeal.shared.contracts.common import AnswerSource
from safemeal.shared.types import JsonObject
from safemeal.modules.recipe_catalog.generation import GeneratedRecipe


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
    # ``default_user`` 会让所有未显式传 user_id 的客户端共享会话和长期记忆。
    # 即使是单机模式，也要求调用方持有一个稳定、唯一的匿名或登录用户 ID。
    user_id: str = Field(..., min_length=1, max_length=255)


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
