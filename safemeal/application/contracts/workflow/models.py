"""Serializable workflow input and state; no Agent implementation imports."""

from __future__ import annotations
from dataclasses import dataclass
from safemeal.shared.types import JsonObject

from typing import Literal, TypedDict
from pydantic import BaseModel, Field
from safemeal.application.contracts.agent.api import AgentProcessResponse
from safemeal.application.contracts.agent.context import AgentContext
from safemeal.application.contracts.conversation.models import ConversationHistory


class WorkflowRequest(BaseModel):
    message: str
    user_id: str
    session_id: str
    history: ConversationHistory = Field(default_factory=list)
    source_message_id: str | None = None
    context: AgentContext | None = None
    use_user_memory: bool = True
    include_trace: bool = False
    resume_approved: bool | None = None


class IntentDecision(BaseModel):
    kind: Literal[
        "recommend",
        "recipe_detail",
        "generate",
        "replace",
        "knowledge",
        "memory",
        "clarify",
        "out_of_scope",
    ]
    reason: str = ""
    clarification: str = ""


class WorkflowState(TypedDict, total=False):
    request: WorkflowRequest
    context: AgentContext
    intent: IntentDecision
    result: AgentProcessResponse
    safety_blocked: bool


@dataclass(frozen=True)
class ConversationContextResult:
    history: ConversationHistory
    episodic_memories: list[JsonObject]
    estimated_tokens: int
    summarized_messages: int
