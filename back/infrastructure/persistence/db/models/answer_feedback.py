"""Durable current-state feedback for persisted Agent answers."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from SafeMealAgent.back.infrastructure.persistence.database import Base


class AnswerFeedback(Base):
    __tablename__ = "answer_feedbacks"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_answer_feedbacks_message"),
        CheckConstraint(
            "rating IN ('positive', 'negative')",
            name="ck_answer_feedbacks_rating",
        ),
        CheckConstraint(
            "review_status IN ('not_required', 'pending_queue', 'pending_review')",
            name="ck_answer_feedbacks_review_status",
        ),
        Index("ix_answer_feedbacks_user_rating", "user_id", "rating"),
    )

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(
        String(255),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id = Column(
        Integer,
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(String(255), nullable=False, index=True)
    rating = Column(String(16), nullable=False, index=True)
    reason = Column(Text, nullable=False, default="")
    corrected_answer = Column(Text, nullable=True)
    review_status = Column(String(32), nullable=False, default="not_required")
    review_sample_id = Column(String(64), nullable=True, index=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
    )


__all__ = ["AnswerFeedback"]
