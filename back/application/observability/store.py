"""Ports and read models for durable Agent trace/audit storage."""

from __future__ import annotations

from typing import Protocol

from SafeMealAgent.back.shared.types import JsonObject


class AgentTraceStore(Protocol):
    def record(self, trace: JsonObject) -> None: ...

    def list_records(
        self,
        *,
        limit: int = 50,
        run_id: str | None = None,
        session_id: str | None = None,
        status: str | None = None,
        decisions_only: bool = False,
    ) -> list[JsonObject]: ...


__all__ = ["AgentTraceStore"]
