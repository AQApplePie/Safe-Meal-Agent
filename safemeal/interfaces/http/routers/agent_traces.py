"""Durable Agent trace and decision-audit queries."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, Query

from safemeal.application.observability.store import AgentTraceStore
from safemeal.interfaces import get_agent_trace_store
from safemeal.shared.types import JsonObject


router = APIRouter(prefix="/observability", tags=["Agent Traces"])


@router.get("/agent-traces")
async def list_agent_traces(
    limit: int = Query(default=50, ge=1, le=500),
    run_id: str | None = Query(default=None, max_length=64),
    session_id: str | None = Query(default=None, max_length=255),
    status: Literal["running", "ok", "error"] | None = None,
    decisions_only: bool = False,
    store: AgentTraceStore = Depends(get_agent_trace_store),
) -> list[JsonObject]:
    """Read the authenticated local trace audit log."""

    return await asyncio.to_thread(
        store.list_records,
        limit=limit,
        run_id=run_id,
        session_id=session_id,
        status=status,
        decisions_only=decisions_only,
    )


__all__ = ["router"]
