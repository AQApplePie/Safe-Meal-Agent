"""Agent input context contract.

This DTO is the single boundary object for data that should accompany one
Agent run.  New context capabilities should be added here and assembled by an
application context builder instead of being threaded through every caller as a
new ``process`` parameter.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from safemeal.application.contracts.conversation.models import ConversationHistory
from safemeal.shared.types import JsonObject


class AgentContext(BaseModel):
    """Structured context consumed by the Agent graph."""

    model_config = ConfigDict(extra="forbid")

    conversation_history: ConversationHistory = Field(
        default_factory=list, max_length=40
    )
    user_memories: list[JsonObject] = Field(default_factory=list)
    user_profile: Optional[JsonObject] = None
    dietary_constraints: Optional[JsonObject] = None
    intent: Optional[str] = None
    episodic_memories: list[JsonObject] = Field(default_factory=list, max_length=100)
    observations: list[JsonObject] = Field(default_factory=list, max_length=50)
    context_metadata: JsonObject = Field(default_factory=dict)

    @field_validator("conversation_history")
    @classmethod
    def validate_conversation_history(
        cls,
        history: ConversationHistory,
    ) -> ConversationHistory:
        allowed_roles = {"user", "assistant", "system"}
        for message in history:
            role = message.get("role", "")
            content = message.get("content", "")
            if role not in allowed_roles:
                raise ValueError(f"unsupported conversation role: {role!r}")
            if not content.strip() or len(content) > 5_000:
                raise ValueError(
                    "conversation message content must contain 1..5000 characters"
                )
        return history


class AgentContextPatch(BaseModel):
    """Partial context returned by one Agent context provider."""

    model_config = ConfigDict(extra="forbid")

    user_memories: list[JsonObject] = Field(default_factory=list)
    user_profile: Optional[JsonObject] = None
    episodic_memories: list[JsonObject] = Field(default_factory=list, max_length=100)
    observations: list[JsonObject] = Field(default_factory=list, max_length=50)
    context_metadata: JsonObject = Field(default_factory=dict)
