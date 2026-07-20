"""Rotating JSONL persistence for successful and failed Agent traces."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Iterator

from SafeMealAgent.back.application.observability.metrics import TRACE_PERSISTENCE
from SafeMealAgent.back.shared.types import JsonObject, to_json_object

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


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
    """Append-only audit store with size rotation and restricted permissions."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_bytes: int = 50_000_000,
        backup_count: int = 5,
    ) -> None:
        self.path = Path(path).resolve(strict=False)
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self._lock = Lock()
        self._lock_path = self.path.with_name(f"{self.path.name}.lock")

    @contextmanager
    def _process_lock(self) -> Iterator[None]:
        descriptor = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            try:
                if fcntl is not None:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _rotate(self, incoming_bytes: int) -> None:
        if (
            not self.path.exists()
            or self.path.stat().st_size + incoming_bytes <= self.max_bytes
        ):
            return
        oldest = self.path.with_name(f"{self.path.name}.{self.backup_count}")
        oldest.unlink(missing_ok=True)
        for index in range(self.backup_count - 1, 0, -1):
            source = self.path.with_name(f"{self.path.name}.{index}")
            target = self.path.with_name(f"{self.path.name}.{index + 1}")
            if source.exists():
                source.replace(target)
        self.path.replace(self.path.with_name(f"{self.path.name}.1"))

    def record(self, trace: JsonObject) -> None:
        record: JsonObject = {
            "run_id": trace.get("run_id"),
            "session_id": trace.get("session_id"),
            "status": trace.get("status"),
            "started_at": trace.get("started_at"),
            "finished_at": trace.get("finished_at"),
            "total_latency_ms": trace.get("total_latency_ms"),
            "token_usage": trace.get("token_usage"),
            "cost_usage": trace.get("cost_usage"),
            "cost_usage_complete": trace.get("cost_usage_complete"),
            "decisions": _decision_events(trace),
            "trace": trace,
        }
        payload = (
            json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self._process_lock():
                    self._rotate(len(payload))
                    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
                    if hasattr(os, "O_CLOEXEC"):
                        flags |= os.O_CLOEXEC
                    descriptor = os.open(self.path, flags, 0o600)
                    try:
                        view = memoryview(payload)
                        while view:
                            written = os.write(descriptor, view)
                            if written <= 0:
                                raise OSError("failed to append Agent trace")
                            view = view[written:]
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
            TRACE_PERSISTENCE.labels(outcome="ok").inc()
        except Exception:
            TRACE_PERSISTENCE.labels(outcome="error").inc()
            raise

    def _paths(self) -> list[Path]:
        paths = [self.path]
        paths.extend(
            self.path.with_name(f"{self.path.name}.{index}")
            for index in range(1, self.backup_count + 1)
        )
        return [path for path in paths if path.exists()]

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
        records: list[JsonObject] = []
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._process_lock():
                for path in self._paths():
                    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
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
                                    "cost_usage",
                                    "cost_usage_complete",
                                    "decisions",
                                )
                            }
                        records.append(to_json_object(value))
                        if len(records) >= limit:
                            return records
        return records


__all__ = ["JsonlAgentTraceStore"]
