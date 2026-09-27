"""Agent Orchestrator application contracts."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from safemeal.application.contracts.agent.context import AgentContext
from safemeal.application.contracts.conversation.models import (
    AnswerSource,
    ConversationMessage,
)
from safemeal.shared.types import JsonObject
from safemeal.modules.recipe_catalog.generated_recipe import GeneratedRecipe


class AgentProcessRequest(BaseModel):
    """供受信任内部服务调用的 Agent 请求。"""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1, max_length=5000)
    session_id: str = Field(..., min_length=1, max_length=255)
    user_id: str = Field(default="internal_user", min_length=1, max_length=255)
    history: List[ConversationMessage] = Field(default_factory=list, max_length=40)
    context: Optional[AgentContext] = Field(
        default=None,
        description="完整 Agent 输入上下文；为空时使用 history/use_user_memory 兼容字段构建。",
    )
    include_trace: bool = False
    use_user_memory: bool = Field(
        default=False,
        description="是否加载并注入长期用户记忆。",
    )


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


class AgentResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=255)
    approved: bool


class AgentResumeResult(BaseModel):
    """Checkpoint context returned with a resumed draft for independent review."""

    response: AgentProcessResponse
    message: str = ""
    context: AgentContext = Field(default_factory=AgentContext)
