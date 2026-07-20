from __future__ import annotations

from datetime import datetime, timezone
import os
import time
from uuid import uuid4

import httpx
import pytest


def test_live_prometheus_alertmanager_receiver_and_grafana() -> None:
    if os.getenv("RUN_MONITORING_INTEGRATION") != "1":
        pytest.skip("set RUN_MONITORING_INTEGRATION=1 after starting monitoring profile")

    prometheus = os.getenv("PROMETHEUS_TEST_URL", "http://127.0.0.1:19090")
    alertmanager = os.getenv("ALERTMANAGER_TEST_URL", "http://127.0.0.1:19093")
    receiver = os.getenv("ALERT_RECEIVER_TEST_URL", "http://127.0.0.1:18090")
    grafana = os.getenv("GRAFANA_TEST_URL", "http://127.0.0.1:13000")
    grafana_auth = (
        os.getenv("GRAFANA_ADMIN_USER", "admin"),
        os.getenv("GRAFANA_ADMIN_PASSWORD", "safemeal-local"),
    )
    alert_name = f"SafeMealIntegration{uuid4().hex[:10]}"

    with httpx.Client(timeout=10) as client:
        targets = client.get(f"{prometheus}/api/v1/targets").json()
        assert any(
            target["labels"].get("job") == "safemeal-api"
            and target["health"] == "up"
            for target in targets["data"]["activeTargets"]
        )
        assert client.get(f"{alertmanager}/-/ready").is_success
        assert client.get(f"{receiver}/health").json() == {"status": "ok"}
        assert client.get(f"{grafana}/api/health").json()["database"] == "ok"
        dashboard = client.get(
            f"{grafana}/api/dashboards/uid/safemeal-agent-overview",
            auth=grafana_auth,
        )
        dashboard.raise_for_status()
        assert dashboard.json()["dashboard"]["panels"]

        before = client.get(f"{receiver}/alerts?limit=500").json()["count"]
        response = client.post(
            f"{alertmanager}/api/v2/alerts",
            json=[
                {
                    "labels": {"alertname": alert_name, "severity": "warning"},
                    "annotations": {"summary": "monitoring integration test"},
                    "generatorURL": "http://localhost/integration-test",
                }
            ],
        )
        response.raise_for_status()
        delivered = False
        for _ in range(15):
            records = client.get(f"{receiver}/alerts?limit=500").json()
            if records["count"] > before and any(
                alert.get("labels", {}).get("alertname") == alert_name
                for record in records["records"]
                for alert in record["payload"].get("alerts", [])
            ):
                delivered = True
                break
            time.sleep(2)
        assert delivered

        client.post(
            f"{alertmanager}/api/v2/alerts",
            json=[
                {
                    "labels": {"alertname": alert_name, "severity": "warning"},
                    "annotations": {"summary": "monitoring integration test"},
                    "generatorURL": "http://localhost/integration-test",
                    "endsAt": datetime.now(timezone.utc).isoformat(),
                }
            ],
        ).raise_for_status()
