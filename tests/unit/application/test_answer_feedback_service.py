from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from SafeMealAgent.back.application.contracts.feedback import (
    AnswerFeedbackRecord,
    AnswerFeedbackStats,
)
from SafeMealAgent.back.application.use_cases.feedback.service import AnswerFeedbackService
from SafeMealAgent.back.shared.contracts.feedback import FailureSample


class Sessions:
    message = SimpleNamespace(
        id=7,
        session_id="s1",
        message_type="agent_response",
        content="回答",
        message_metadata={"model": "test"},
        order_index=2,
    )

    def get_message(self, message_id: int, *, user_id: str):
        return self.message if message_id == 7 and user_id == "u1" else None

    def get_question_before_message(self, message, *, user_id: str):
        return "问题"


class Repository:
    def __init__(self) -> None:
        self.current: AnswerFeedbackRecord | None = None

    def get(self, message_id: int, *, user_id: str):
        return self.current

    def upsert(self, data):
        now = datetime.now(timezone.utc)
        self.current = AnswerFeedbackRecord(
            id=1,
            created_at=now,
            updated_at=now,
            **data.model_dump(),
        )
        return self.current

    def mark_review_queued(self, message_id: int, *, user_id: str, sample_id: str):
        assert self.current is not None
        self.current = self.current.model_copy(
            update={"review_status": "pending_review", "review_sample_id": sample_id}
        )
        return self.current

    def stats(self, *, user_id: str):
        rating = self.current.rating if self.current else None
        return AnswerFeedbackStats(
            total=int(rating is not None),
            positive=int(rating == "positive"),
            negative=int(rating == "negative"),
            pending_review=int(
                bool(self.current and self.current.review_status == "pending_review")
            ),
            positive_rate=1.0 if rating == "positive" else 0.0 if rating else None,
        )


class Collector:
    def __init__(self) -> None:
        self.calls = 0

    def record_negative_feedback(self, **kwargs):
        self.calls += 1
        return FailureSample(
            id=f"sample-{self.calls}",
            event_type="negative_feedback",
            session_id=kwargs["session_id"],
            message_id=kwargs["message_id"],
            question=kwargs["question"],
            answer=kwargs["answer"],
            reason=kwargs["reason"],
        )


def service(repository: Repository, collector: Collector) -> AnswerFeedbackService:
    return AnswerFeedbackService(
        session_management=Sessions(),  # type: ignore[arg-type]
        repository=repository,  # type: ignore[arg-type]
        collector=collector,  # type: ignore[arg-type]
    )


def test_positive_feedback_is_persisted_and_counted() -> None:
    repository, collector = Repository(), Collector()

    result = service(repository, collector).submit(
        session_id="s1", message_id=7, user_id="u1", rating="positive"
    )

    assert result.feedback.rating == "positive"
    assert result.feedback.review_status == "not_required"
    assert not result.queued_for_review
    assert collector.calls == 0
    assert service(repository, collector).stats(user_id="u1").positive == 1


def test_identical_negative_feedback_is_queued_exactly_once() -> None:
    repository, collector = Repository(), Collector()
    use_case = service(repository, collector)

    first = use_case.submit(
        session_id="s1",
        message_id=7,
        user_id="u1",
        rating="negative",
        reason="不准确",
    )
    second = use_case.submit(
        session_id="s1",
        message_id=7,
        user_id="u1",
        rating="negative",
        reason="不准确",
    )

    assert first.feedback.review_sample_id == "sample-1"
    assert second.feedback.review_sample_id == "sample-1"
    assert collector.calls == 1
    assert use_case.stats(user_id="u1").pending_review == 1
