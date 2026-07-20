"""Persist answer feedback and route negative samples for review."""

from __future__ import annotations

from dataclasses import dataclass

from SafeMealAgent.back.application.contracts.feedback import (
    AnswerFeedbackRecord,
    AnswerFeedbackStats,
    AnswerFeedbackWrite,
    FeedbackRating,
)
from SafeMealAgent.back.application.ports.feedback_repository import AnswerFeedbackRepository
from SafeMealAgent.back.application.use_cases.chat.session_management_service import (
    SessionManagementService,
)
from SafeMealAgent.back.shared.contracts.feedback import FailureCollector


class FeedbackTargetNotFoundError(LookupError):
    """The requested answer is absent or is owned by another user."""


class FeedbackTargetInvalidError(ValueError):
    """The target exists but is not an Agent answer."""


class FeedbackTargetConflictError(RuntimeError):
    """The answer cannot be associated with its original question."""


@dataclass(frozen=True)
class FeedbackSubmission:
    feedback: AnswerFeedbackRecord
    queued_for_review: bool


class AnswerFeedbackService:
    def __init__(
        self,
        *,
        session_management: SessionManagementService,
        repository: AnswerFeedbackRepository,
        collector: FailureCollector,
    ) -> None:
        self._sessions = session_management
        self._repository = repository
        self._collector = collector

    def submit(
        self,
        *,
        session_id: str,
        message_id: int,
        user_id: str,
        rating: FeedbackRating,
        reason: str = "",
        corrected_answer: str | None = None,
    ) -> FeedbackSubmission:
        message = self._sessions.get_message(message_id, user_id=user_id)
        if message is None or message.session_id != session_id:
            raise FeedbackTargetNotFoundError
        if message.message_type != "agent_response":
            raise FeedbackTargetInvalidError

        question = self._sessions.get_question_before_message(
            message,
            user_id=user_id,
        )
        if not question:
            raise FeedbackTargetConflictError

        previous = self._repository.get(message_id, user_id=user_id)
        queue_is_current = bool(
            previous
            and previous.rating == "negative"
            and previous.review_status == "pending_review"
            and previous.reason == reason
            and previous.corrected_answer == corrected_answer
        )
        feedback = self._repository.upsert(
            AnswerFeedbackWrite(
                session_id=session_id,
                message_id=message_id,
                user_id=user_id,
                rating=rating,
                reason=reason,
                corrected_answer=corrected_answer,
                review_status=(
                    "pending_review"
                    if rating == "negative" and queue_is_current
                    else "pending_queue"
                    if rating == "negative"
                    else "not_required"
                ),
                review_sample_id=(
                    previous.review_sample_id
                    if rating == "negative" and queue_is_current and previous
                    else None
                ),
            )
        )
        if rating == "positive":
            return FeedbackSubmission(feedback=feedback, queued_for_review=False)
        if queue_is_current:
            return FeedbackSubmission(feedback=feedback, queued_for_review=True)

        # Persist pending_queue first. If the append fails, a retry will enqueue it
        # instead of silently losing a negative sample.
        sample = self._collector.record_negative_feedback(
            session_id=session_id,
            message_id=str(message_id),
            question=question,
            answer=message.content,
            reason=reason or "用户标记回答不满意",
            corrected_answer=corrected_answer,
            metadata=message.message_metadata or {},
        )
        feedback = self._repository.mark_review_queued(
            message_id,
            user_id=user_id,
            sample_id=sample.id,
        )
        return FeedbackSubmission(feedback=feedback, queued_for_review=True)

    def stats(self, *, user_id: str) -> AnswerFeedbackStats:
        return self._repository.stats(user_id=user_id)


__all__ = [
    "AnswerFeedbackService",
    "FeedbackSubmission",
    "FeedbackTargetConflictError",
    "FeedbackTargetInvalidError",
    "FeedbackTargetNotFoundError",
]
