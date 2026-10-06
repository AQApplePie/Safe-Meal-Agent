"""实现 HTTP 接口层的请求与响应适配。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ChatSessionUpdateRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def require_change(self) -> "ChatSessionUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("at least one session field must be provided")
        if "title" in self.model_fields_set and self.title is None:
            raise ValueError("title cannot be null")
        if "is_active" in self.model_fields_set and self.is_active is None:
            raise ValueError("is_active cannot be null")
        return self


class ChatSessionResponse(BaseModel):

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    user_id: str
    created_at: datetime
    updated_at: Optional[datetime]
    is_active: bool

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def normalize_utc(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


__all__ = [
    "ChatSessionResponse",
    "ChatSessionUpdateRequest",
]
