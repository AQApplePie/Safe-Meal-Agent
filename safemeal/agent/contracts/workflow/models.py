"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations
from dataclasses import dataclass
from safemeal.shared.types import JsonObject
from safemeal.modules.dietary.contracts.requirements import (
    DietaryRequirements,
)

from typing import TypedDict
from pydantic import BaseModel, Field
from safemeal.agent.contracts.api import AgentProcessResponse
from safemeal.agent.contracts.context import AgentContext
from safemeal.modules.conversation.contracts.conversation.models import ConversationHistory
from safemeal.shared.contracts.request_frame import RequestFrame
from safemeal.modules.dietary.contracts.control_plane import (
    ResolvedConstraints,
)


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
    resolved_constraints: ResolvedConstraints
    request_frame: RequestFrame
    recent_history: ConversationHistory
    active_menu: JsonObject | None


@dataclass(frozen=True)
class ConversationContextResult:
    history: ConversationHistory
    episodic_memories: list[JsonObject]
    estimated_tokens: int
    summarized_messages: int
