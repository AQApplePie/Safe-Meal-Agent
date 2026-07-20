"""Persistence port for current answer-feedback state."""

from __future__ import annotations

from typing import Protocol

from SafeMealAgent.back.application.contracts.feedback import (
    AnswerFeedbackRecord,
    AnswerFeedbackStats,
    AnswerFeedbackWrite,
)


class AnswerFeedbackRepository(Protocol):
    def get(self, message_id: int, *, user_id: str) -> AnswerFeedbackRecord | None: ...

    def upsert(self, data: AnswerFeedbackWrite) -> AnswerFeedbackRecord: ...

    def mark_review_queued(
        self,
        message_id: int,
        *,
        user_id: str,
        sample_id: str,
    ) -> AnswerFeedbackRecord: ...

    def stats(self, *, user_id: str) -> AnswerFeedbackStats: ...


__all__ = ["AnswerFeedbackRepository"]
