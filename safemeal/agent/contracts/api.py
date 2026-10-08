"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from safemeal.agent.contracts.context import AgentContext
from safemeal.modules.conversation.contracts.conversation.models import (
    AnswerSource,
)
from safemeal.agent.contracts.intent import IntentDecision
from safemeal.shared.types import JsonObject
from safemeal.modules.recipe.contracts.generated import GeneratedRecipe


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

    response: AgentProcessResponse
    message: str = ""
    context: AgentContext = Field(default_factory=AgentContext)
