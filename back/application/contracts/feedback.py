"""Application contracts for durable answer feedback."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


FeedbackRating = Literal["positive", "negative"]
FeedbackReviewStatus = Literal["not_required", "pending_queue", "pending_review"]


class AnswerFeedbackWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=255)
    message_id: int = Field(ge=1)
    user_id: str = Field(min_length=1, max_length=255)
    rating: FeedbackRating
    reason: str = Field(default="", max_length=2_000)
    corrected_answer: str | None = Field(default=None, max_length=10_000)
    review_status: FeedbackReviewStatus = "not_required"
    review_sample_id: str | None = Field(default=None, max_length=64)


class AnswerFeedbackRecord(AnswerFeedbackWrite):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime | None = None


class AnswerFeedbackStats(BaseModel):
    total: int = 0
    positive: int = 0
    negative: int = 0
    pending_review: int = 0
    positive_rate: float | None = None


__all__ = [
    "AnswerFeedbackRecord",
    "AnswerFeedbackStats",
    "AnswerFeedbackWrite",
    "FeedbackRating",
    "FeedbackReviewStatus",
]
