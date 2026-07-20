"""SQLAlchemy adapter for durable answer feedback and statistics."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from SafeMealAgent.back.application.contracts.feedback import (
    AnswerFeedbackRecord,
    AnswerFeedbackStats,
    AnswerFeedbackWrite,
)
from SafeMealAgent.back.application.ports.feedback_repository import AnswerFeedbackRepository
from SafeMealAgent.back.infrastructure.persistence.database import session_scope
from SafeMealAgent.back.infrastructure.persistence.db.models import AnswerFeedback


class SqlAlchemyAnswerFeedbackRepository:
    def __init__(self, session_factory: Callable[[], Session] | None = None) -> None:
        self._session_factory = session_factory

    def get(self, message_id: int, *, user_id: str) -> AnswerFeedbackRecord | None:
        with session_scope(
            commit=False, session_factory=self._session_factory
        ) as session:
            entity = (
                session.query(AnswerFeedback)
                .filter(
                    AnswerFeedback.message_id == message_id,
                    AnswerFeedback.user_id == user_id,
                )
                .one_or_none()
            )
            return (
                AnswerFeedbackRecord.model_validate(entity)
                if entity is not None
                else None
            )

    def upsert(self, data: AnswerFeedbackWrite) -> AnswerFeedbackRecord:
        with session_scope(session_factory=self._session_factory) as session:
            entity = (
                session.query(AnswerFeedback)
                .filter(AnswerFeedback.message_id == data.message_id)
                .with_for_update()
                .one_or_none()
            )
            payload = data.model_dump()
            if entity is None:
                entity = AnswerFeedback(**payload)
                session.add(entity)
            else:
                if entity.user_id != data.user_id or entity.session_id != data.session_id:
                    raise ValueError("feedback target ownership cannot be changed")
                for field, value in payload.items():
                    setattr(entity, field, value)
                entity.updated_at = datetime.now(timezone.utc)
            session.flush()
            return AnswerFeedbackRecord.model_validate(entity)

    def mark_review_queued(
        self,
        message_id: int,
        *,
        user_id: str,
        sample_id: str,
    ) -> AnswerFeedbackRecord:
        with session_scope(session_factory=self._session_factory) as session:
            entity = (
                session.query(AnswerFeedback)
                .filter(
                    AnswerFeedback.message_id == message_id,
                    AnswerFeedback.user_id == user_id,
                )
                .with_for_update()
                .one()
            )
            entity.review_status = "pending_review"
            entity.review_sample_id = sample_id
            entity.updated_at = datetime.now(timezone.utc)
            session.flush()
            return AnswerFeedbackRecord.model_validate(entity)

    def stats(self, *, user_id: str) -> AnswerFeedbackStats:
        with session_scope(
            commit=False, session_factory=self._session_factory
        ) as session:
            grouped = dict(
                session.query(AnswerFeedback.rating, func.count(AnswerFeedback.id))
                .filter(AnswerFeedback.user_id == user_id)
                .group_by(AnswerFeedback.rating)
                .all()
            )
            pending = int(
                session.query(func.count(AnswerFeedback.id))
                .filter(
                    AnswerFeedback.user_id == user_id,
                    AnswerFeedback.review_status.in_(("pending_queue", "pending_review")),
                )
                .scalar()
                or 0
            )
        positive = int(grouped.get("positive", 0))
        negative = int(grouped.get("negative", 0))
        total = positive + negative
        return AnswerFeedbackStats(
            total=total,
            positive=positive,
            negative=negative,
            pending_review=pending,
            positive_rate=round(positive / total, 6) if total else None,
        )


def sqlalchemy_answer_feedback_repository() -> AnswerFeedbackRepository:
    return SqlAlchemyAnswerFeedbackRepository()


__all__ = [
    "SqlAlchemyAnswerFeedbackRepository",
    "sqlalchemy_answer_feedback_repository",
]
