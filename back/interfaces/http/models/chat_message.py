"""HTTP-only request and response schemas for chat messages."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from SafeMealAgent.back.shared.types import JsonObject


MessageType = Literal["user_query", "agent_response", "knowledge", "error"]


class ChatMessageResponse(BaseModel):
    """Serialized persisted message."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: str
    message_type: MessageType
    content: str
    message_metadata: Optional[JsonObject] = None
    order_index: int
    client_request_id: Optional[str] = None
    reply_to_message_id: Optional[int] = None
    turn_status: Optional[Literal["processing", "completed", "failed"]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

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
