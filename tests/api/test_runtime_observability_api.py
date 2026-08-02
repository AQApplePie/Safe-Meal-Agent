"""HTTP boundary tests for runtime observability."""

from __future__ import annotations

from fastapi.testclient import TestClient

from safemeal.config import settings
from safemeal.interfaces.http.dependencies import get_agent_trace_store
from safemeal.main import create_application


class _TraceStore:
    def record(self, trace: dict) -> None:
        return None

    def list_records(self, **kwargs: object) -> list[dict]:
        return [
            {
                "run_id": "run-1",
                "status": "ok",
                "decisions": [{"stage": "planner", "route": "tools"}],
            }
        ]


def test_internal_decision_audit_endpoint_is_available(monkeypatch) -> None:
    monkeypatch.setattr(settings, "API_KEY", None)
    monkeypatch.setattr(settings, "REDIS_RATE_LIMIT_URL", None)
    application = create_application()
    application.dependency_overrides[get_agent_trace_store] = _TraceStore

    with TestClient(application) as client:
        traces = client.get("/api/v1/observability/agent-traces?decisions_only=true")

    assert traces.status_code == 200
    assert traces.json()[0]["decisions"][0]["stage"] == "planner"


def test_decision_audit_endpoint_requires_configured_api_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "API_KEY", "local-secret")
    monkeypatch.setattr(settings, "REDIS_RATE_LIMIT_URL", None)
    application = create_application()
    application.dependency_overrides[get_agent_trace_store] = _TraceStore

    with TestClient(application) as client:
        response = client.get("/api/v1/observability/agent-traces")

    assert response.status_code == 401
