"""
Pydantic request/response models used by the HTTP API layer.

This package consolidates what used to live under ``back.schemas`` so that the
name makes their purpose (API-facing contracts) explicit.
"""

from .chat_message import ChatMessageResponse
from .chat_session import (
    ChatSessionCreateRequest,
    ChatSessionResponse,
    ChatSessionUpdateRequest,
)
from .knowledge import RecipeModel, SearchRequest, SearchResponse
from .lightrag import (
    LightRAGInsertRequest,
    LightRAGInsertResponse,
    LightRAGQueryRequest,
    LightRAGQueryResponse,
)
from .memory import (
    UserMemoryCreateRequest,
    UserMemoryRememberRequest,
    UserMemoryResponse,
    UserMemoryUpdateRequest,
)
from .upload import UploadResponse

__all__ = [
    "ChatMessageResponse",
    "ChatSessionCreateRequest",
    "ChatSessionResponse",
    "ChatSessionUpdateRequest",
    "RecipeModel",
    "SearchRequest",
    "SearchResponse",
    "LightRAGInsertRequest",
    "LightRAGInsertResponse",
    "LightRAGQueryRequest",
    "LightRAGQueryResponse",
    "UserMemoryCreateRequest",
    "UserMemoryRememberRequest",
    "UserMemoryResponse",
    "UserMemoryUpdateRequest",
    "UploadResponse",
]
