from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from SafeMealAgent.back.application.use_cases.chat.persistence_service import ChatPersistenceService
from SafeMealAgent.back.infrastructure.persistence.chat_repository import sqlalchemy_chat_unit_of_work
from SafeMealAgent.back.infrastructure.persistence.database import session_scope
from SafeMealAgent.back.infrastructure.persistence.db.models import ChatSession
from SafeMealAgent.back.infrastructure.persistence.feedback_repository import (
    SqlAlchemyAnswerFeedbackRepository,
)


def test_live_positive_negative_feedback_persistence_and_stats() -> None:
    if os.getenv("RUN_FEEDBACK_INTEGRATION") != "1":
        pytest.skip("set RUN_FEEDBACK_INTEGRATION=1 against a running API")

    api = os.getenv("FEEDBACK_TEST_API_URL", "http://127.0.0.1:8000")
    secret = os.environ["AUTH_GATEWAY_SECRET"]
    user_id = f"feedback-integration-{uuid4().hex}"
    persistence = ChatPersistenceService(sqlalchemy_chat_unit_of_work)
    turn = persistence.start_turn(
        None,
        user_id,
        "测试问题",
        request_id=uuid4().hex,
    )
    message_id = int(
        persistence.save_agent_response(
            session_id=turn.session_id,
            user_id=user_id,
            user_message_id=turn.user_message_id,
            response_order_index=turn.response_order_index,
            response="测试回答",
        )
    )
    headers = {
        "X-SafeMeal-Gateway-Secret": secret,
        "X-SafeMeal-User-ID": user_id,
        "X-SafeMeal-Roles": "user",
    }
    base_payload = {
        "session_id": turn.session_id,
        "message_id": str(message_id),
        "user_id": user_id,
    }

    try:
        sample_id: str | None = None
        with httpx.Client(base_url=api, headers=headers, timeout=15) as client:
            positive = client.post(
                "/api/v1/feedback/",
                json={**base_payload, "rating": "positive"},
            )
            positive.raise_for_status()
            assert positive.json()["queued_for_review"] is False
            stats = client.get(
                "/api/v1/feedback/stats", params={"user_id": user_id}
            )
            stats.raise_for_status()
            assert stats.json()["positive"] == 1
            assert stats.json()["positive_rate"] == 1.0

            negative = client.post(
                "/api/v1/feedback/",
                json={
                    **base_payload,
                    "rating": "negative",
                    "reason": "集成测试负反馈",
                },
            )
            negative.raise_for_status()
            assert negative.json()["queued_for_review"] is True
            sample_id = negative.json()["sample_id"]
            assert sample_id

        record = SqlAlchemyAnswerFeedbackRepository().get(
            message_id, user_id=user_id
        )
        assert record is not None
        assert record.rating == "negative"
        assert record.review_status == "pending_review"
    finally:
        with session_scope() as session:
            session.query(ChatSession).filter(
                ChatSession.id == turn.session_id
            ).delete()
        queue_path = Path(
            os.getenv(
                "FEEDBACK_TEST_QUEUE_PATH", "data/runtime/online_failures.jsonl"
            )
        )
        if sample_id and queue_path.exists():
            retained = [
                line
                for line in queue_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and json.loads(line).get("id") != sample_id
            ]
            if retained:
                queue_path.write_text("\n".join(retained) + "\n", encoding="utf-8")
            else:
                queue_path.unlink()
