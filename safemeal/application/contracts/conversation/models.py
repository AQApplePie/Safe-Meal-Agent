"""Agent conversation and answer contracts shared across layers."""

from __future__ import annotations

from typing import Optional, TypeAlias

from pydantic import BaseModel, Field

ConversationMessage: TypeAlias = dict[str, str]
ConversationHistory: TypeAlias = list[ConversationMessage]


class AnswerSource(BaseModel):
    """最终答案引用的来源信息。"""

    source: str = Field(
        description="来源名称，例如 mysql:recipes、retrieval 或文档路径。"
    )
    tool: str = Field(default="", description="产生该来源的工具名。")
    call_id: str = Field(default="", description="对应工具调用 ID。")
    query: Optional[str] = Field(default=None, description="可选 SQL/Cypher/检索查询。")
    evidence_call_ids: list[str] = Field(
        default_factory=list,
        description="聚合来源时关联的底层证据调用 ID。",
    )


class RouterInfo(BaseModel):
    """Agent 最终路由说明。"""

    type: str = Field(description="路由类型，例如 agent-tools-loop。")
    logic: str = Field(description="本轮路由或反思理由。")
