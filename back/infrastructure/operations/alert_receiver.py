"""Durable Alertmanager webhook receiver with optional external forwarding."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import Lock
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field


class AlertmanagerWebhook(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = Field(default="unknown", max_length=32)
    receiver: str = Field(default="", max_length=255)
    groupKey: str = Field(default="", max_length=2_000)
    alerts: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


class AlertInbox:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = Lock()

    def append(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._path.open("a", encoding="utf-8") as output:
            output.write(line + "\n")
            output.flush()

    def tail(self, limit: int) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        with self._lock, self._path.open("r", encoding="utf-8") as source:
            lines = source.readlines()[-limit:]
        return [json.loads(line) for line in lines if line.strip()]


app = FastAPI(title="SafeMeal Agent Alert Receiver", version="1.0")
inbox = AlertInbox(
    Path(os.getenv("ALERT_INBOX_PATH", "/app/data/runtime/alerts.jsonl"))
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/alerts", status_code=202)
def receive_alerts(webhook: AlertmanagerWebhook) -> dict[str, Any]:
    payload = webhook.model_dump(mode="json")
    envelope = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "status": webhook.status,
        "group_key": webhook.groupKey,
        "alert_count": len(webhook.alerts),
        "payload": payload,
    }
    inbox.append(envelope)

    forward_url = os.getenv("ALERT_NOTIFICATION_WEBHOOK_URL", "").strip()
    if forward_url:
        headers: dict[str, str] = {}
        token = os.getenv("ALERT_NOTIFICATION_WEBHOOK_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(forward_url, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            # The durable inbox remains the source of truth; returning an error
            # asks Alertmanager to retry external delivery.
            raise HTTPException(status_code=502, detail="external forwarding failed") from exc
    return {"accepted": True, "stored": True, "alerts": len(webhook.alerts)}


@app.get("/alerts")
def list_alerts(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
    records = inbox.tail(limit)
    return {"count": len(records), "records": records}
