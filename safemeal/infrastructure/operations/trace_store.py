"""Small append-only JSONL store for local Agent traces."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from safemeal.shared.types import JsonObject, to_json_object


def _decision_events(trace: JsonObject) -> list[JsonObject]:
    events: list[JsonObject] = []
    spans = trace.get("spans")
    for span in spans if isinstance(spans, list) else []:
        if not isinstance(span, dict) or span.get("name") not in {
            "planner",
            "reflect",
            "respond",
        }:
            continue
        output_value = span.get("output")
        output: dict = output_value if isinstance(output_value, dict) else {}
        events.append(
            {
                "stage": span.get("name"),
                "started_at": span.get("started_at"),
                "duration_ms": span.get("duration_ms"),
                "status": span.get("status"),
                "route": output.get("route"),
                "rationale": output.get("planning_rationale")
                or output.get("reflection_rationale"),
                "pending_tools": [
                    call.get("tool_name")
                    for call in output.get("pending_calls", [])
                    if isinstance(call, dict)
                ],
                "evidence_sufficient": output.get("evidence_sufficient"),
                "loop_stop_reason": output.get("loop_stop_reason"),
            }
        )
    return events


class JsonlAgentTraceStore:
    """Persist and query traces for a single-host portfolio deployment."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve(strict=False)
        self._lock = Lock()

    def record(self, trace: JsonObject) -> None:
        record: JsonObject = {
            "run_id": trace.get("run_id"),
            "session_id": trace.get("session_id"),
            "status": trace.get("status"),
            "started_at": trace.get("started_at"),
            "finished_at": trace.get("finished_at"),
            "total_latency_ms": trace.get("total_latency_ms"),
            "token_usage": trace.get("token_usage"),
            "decisions": _decision_events(trace),
            "trace": trace,
        }
        payload = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(payload + "\n")

    def list_records(
        self,
        *,
        limit: int = 50,
        run_id: str | None = None,
        session_id: str | None = None,
        status: str | None = None,
        decisions_only: bool = False,
    ) -> list[JsonObject]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if not self.path.exists():
            return []
        records: list[JsonObject] = []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                continue
            if run_id and value.get("run_id") != run_id:
                continue
            if session_id and value.get("session_id") != session_id:
                continue
            if status and value.get("status") != status:
                continue
            if decisions_only:
                value = {
                    key: value.get(key)
                    for key in (
                        "run_id",
                        "session_id",
                        "status",
                        "started_at",
                        "finished_at",
                        "total_latency_ms",
                        "token_usage",
                        "decisions",
                    )
                }
            records.append(to_json_object(value))
            if len(records) >= limit:
                break
        return records


__all__ = ["JsonlAgentTraceStore"]
