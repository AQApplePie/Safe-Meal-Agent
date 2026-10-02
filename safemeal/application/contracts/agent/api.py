"""Agent Orchestrator application contracts."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from safemeal.application.contracts.agent.context import AgentContext
from safemeal.application.contracts.conversation.models import (
    AnswerSource,
)
from safemeal.application.contracts.agent.intent import IntentDecision
from safemeal.shared.types import JsonObject
from safemeal.application.contracts.recipes.generated import GeneratedRecipe


class AgentProcessResponse(BaseModel):
    """Agent 内部处理响应。"""

    status: Literal["ok", "degraded", "error"] = "ok"
    message: str
    route: Optional[str] = None
    route_logic: Optional[str] = None
    sources: List[AnswerSource] = Field(default_factory=list)
    metadata: JsonObject = Field(default_factory=dict)
    error_code: Optional[str] = None
    recipe: Optional[GeneratedRecipe] = None
    evidence: list[JsonObject] = Field(default_factory=list)
    intent: IntentDecision | None = None


class AgentResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=255)
    approved: bool


class AgentResumeResult(BaseModel):
    """Checkpoint context returned with a resumed draft for independent review."""

    response: AgentProcessResponse
    message: str = ""
    context: AgentContext = Field(default_factory=AgentContext)
