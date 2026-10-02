"""
Pydantic request/response models used by the HTTP API layer.

This package consolidates what used to live under ``safemeal.schemas`` so that the
name makes their purpose (API-facing contracts) explicit.
"""

from .chat_message import ChatMessageResponse
from .chat_session import (
    ChatSessionResponse,
    ChatSessionUpdateRequest,
)
from .memory import (
    UserMemoryResponse,
    UserMemoryUpdateRequest,
)

__all__ = [
    "ChatMessageResponse",
    "ChatSessionResponse",
    "ChatSessionUpdateRequest",
    "UserMemoryResponse",
    "UserMemoryUpdateRequest",
]
