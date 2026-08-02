"""HTTP models for user memory endpoints."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from safemeal.shared.contracts.memory import (
    MemoryStatus,
    MemoryType,
    UserMemoryRead,
)
from safemeal.shared.types import JsonObject


class UserMemoryCreateRequest(BaseModel):
    """手动创建长期记忆的 HTTP 请求体。"""

    user_id: str = Field(..., min_length=1, max_length=255)
    memory_type: MemoryType
    memory_key: str = Field(..., min_length=1, max_length=255)
    memory_value: str = Field(..., min_length=1, max_length=1_000)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    memory_metadata: Optional[JsonObject] = None


class UserMemoryRememberRequest(BaseModel):
    """从用户消息中抽取长期记忆的请求体。"""

    user_id: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1, max_length=5000)
    source_session_id: Optional[str] = Field(default=None, max_length=255)
    source_message_id: Optional[str] = Field(default=None, max_length=255)


class UserMemoryUpdateRequest(BaseModel):
    """更新长期记忆的 HTTP 请求体。"""

    memory_value: Optional[str] = Field(default=None, min_length=1)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    status: Optional[MemoryStatus] = None
    memory_metadata: Optional[JsonObject] = None


class UserMemoryResponse(UserMemoryRead):
    """长期记忆 HTTP 响应体。"""
