"""Serializable workflow input and state; no Agent implementation imports."""

from __future__ import annotations
from dataclasses import dataclass
from safemeal.shared.types import JsonObject
from safemeal.application.contracts.dietary_safety.requirements import (
    DietaryRequirements,
)

from typing import TypedDict
from pydantic import BaseModel, Field
from safemeal.application.contracts.agent.api import AgentProcessResponse
from safemeal.application.contracts.agent.context import AgentContext
from safemeal.application.contracts.conversation.models import ConversationHistory
from safemeal.application.contracts.workflow.request_frame import RequestFrame


class WorkflowRequest(BaseModel):
    message: str
    user_id: str
    session_id: str
    history: ConversationHistory = Field(default_factory=list)
    source_message_id: str | None = None
    context: AgentContext | None = None
    use_user_memory: bool = True
    resume_approved: bool | None = None


class WorkflowState(TypedDict, total=False):
    request: WorkflowRequest
    context: AgentContext
    result: AgentProcessResponse
    requirements: DietaryRequirements
    request_frame: RequestFrame
    recent_history: ConversationHistory


@dataclass(frozen=True)
class ConversationContextResult:
    history: ConversationHistory
    episodic_memories: list[JsonObject]
    estimated_tokens: int
    summarized_messages: int
