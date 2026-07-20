"""Agent Orchestrator 内部跨服务契约。"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from SafeMealAgent.back.shared.contracts.agent_context import AgentContext
from SafeMealAgent.back.shared.contracts.common import AnswerSource, ConversationMessage
from SafeMealAgent.back.shared.types import JsonObject
from SafeMealAgent.back.application.domain.recipe_generation import GeneratedRecipe


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
