"""HTTP boundary tests for runtime observability."""

from __future__ import annotations

from fastapi.testclient import TestClient

from back.config import settings
from SafeMealAgent.back.interfaces.http.dependencies import get_agent_trace_store
from SafeMealAgent.back.main import create_application


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


def test_internal_decision_audit_endpoint_and_metrics_are_available(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "AUTH_MODE", "disabled")
    application = create_application()
    application.dependency_overrides[get_agent_trace_store] = _TraceStore

    with TestClient(application) as client:
        traces = client.get("/api/v1/observability/agent-traces?decisions_only=true")
        metrics = client.get("/metrics")

    assert traces.status_code == 200
    assert traces.json()[0]["decisions"][0]["stage"] == "planner"
    assert metrics.status_code == 200
    assert "safemeal_agent_runs_total" in metrics.text
    assert "safemeal_distributed_queue_wait_seconds" in metrics.text


def test_decision_audit_endpoint_requires_internal_role(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_MODE", "trusted_gateway")
    monkeypatch.setattr(settings, "AUTH_GATEWAY_SECRET", "x" * 32)
    application = create_application()
    application.dependency_overrides[get_agent_trace_store] = _TraceStore

    with TestClient(application) as client:
        response = client.get("/api/v1/observability/agent-traces")

    assert response.status_code == 401
