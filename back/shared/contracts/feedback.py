"""Online product feedback and failure collection contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from SafeMealAgent.back.shared.types import JsonObject


class FailureSample(BaseModel):
    """等待人工审核的线上失败样本。"""

    id: str = Field(
        default_factory=lambda: uuid4().hex,
        description="回流样本唯一 ID。",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="样本创建时间。",
    )
    event_type: Literal["agent_error", "negative_feedback"] = Field(
        description="失败来源类型。",
    )
    status: Literal["pending_review"] = Field(
        default="pending_review",
        description="固定为待人工审核。",
    )
    session_id: str = Field(min_length=1, max_length=255, description="原业务会话 ID。")
    message_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="原 Agent 消息 ID。",
    )
    question: str = Field(max_length=5_000, description="触发失败的用户问题。")
    answer: str = Field(default="", max_length=10_000, description="原 Agent 回答。")
    reason: str = Field(max_length=2_000, description="错误或负反馈原因。")
    corrected_answer: Optional[str] = Field(
        default=None,
        max_length=10_000,
        description="用户提供的可选纠正答案。",
    )
    trace_summary: JsonObject = Field(
        default_factory=dict,
        description="脱敏后的运行诊断摘要。",
    )
    metadata: JsonObject = Field(
        default_factory=dict,
        description="允许持久化的少量业务标签。",
    )


class FailureCollector(Protocol):
    """失败样本收集端口。"""

    def record_agent_error(
        self,
        *,
        session_id: str,
        question: str,
        reason: str,
        trace: JsonObject,
    ) -> FailureSample:
        """记录 Agent 执行异常。"""

    def record_negative_feedback(
        self,
        *,
        session_id: str,
        message_id: str,
        question: str,
        answer: str,
        reason: str,
        corrected_answer: Optional[str] = None,
        metadata: Optional[JsonObject] = None,
    ) -> FailureSample:
        """记录用户对已持久化 Agent 回答的负反馈。"""


class AnswerFeedbackRequest(BaseModel):
    """用户答案反馈请求。"""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=255)
    message_id: str = Field(min_length=1, max_length=255)
    user_id: str = Field(min_length=1, max_length=255)
    rating: Literal["positive", "negative"]
    reason: str = Field(default="", max_length=2_000)
    corrected_answer: Optional[str] = Field(default=None, max_length=10_000)


class AnswerFeedbackResponse(BaseModel):
    """用户答案反馈响应。"""

    accepted: bool
    queued_for_review: bool
    feedback_id: int
    sample_id: Optional[str] = None


class AnswerFeedbackStatsResponse(BaseModel):
    """当前用户的持久化反馈汇总。"""

    total: int
    positive: int
    negative: int
    pending_review: int
    positive_rate: Optional[float] = None


__all__ = [
    "FailureSample",
    "FailureCollector",
    "AnswerFeedbackRequest",
    "AnswerFeedbackResponse",
    "AnswerFeedbackStatsResponse",
]
