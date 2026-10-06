"""实现 HTTP 接口层的请求与响应适配。"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from safemeal.application.contracts.memory.models import (
    MemoryStatus,
    UserMemoryRead,
)
from safemeal.shared.types import JsonObject


class UserMemoryUpdateRequest(BaseModel):
    """更新长期记忆的 HTTP 请求体。"""

    memory_value: Optional[str] = Field(default=None, min_length=1)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    status: Optional[MemoryStatus] = None
    memory_metadata: Optional[JsonObject] = None


class UserMemoryResponse(UserMemoryRead):
    """长期记忆 HTTP 响应体。"""
