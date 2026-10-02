"""Deterministic safeguards for Agent tools loops."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Iterable, Sequence

from safemeal.application.runtime_budget import (
    current_model_token_usage,
    current_model_cost_usage,
)
from safemeal.application.contracts.agent.decisions import ToolCall


def tool_call_signature(call: ToolCall) -> str:
    payload = json.dumps(
        call.arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(f"{call.tool_name}:{payload}".encode("utf-8")).hexdigest()


def filter_new_tool_calls(
    calls: Sequence[ToolCall],
    *,
    executed_signatures: Iterable[str],
    remaining_calls: int,
) -> tuple[list[ToolCall], int]:
    seen = set(executed_signatures)
    accepted: list[ToolCall] = []
    duplicates = 0
    for call in calls:
        signature = tool_call_signature(call)
        if signature in seen:
            duplicates += 1
            continue
        if len(accepted) >= max(0, remaining_calls):
            break
        seen.add(signature)
        accepted.append(call)
    return accepted, duplicates


__all__ = [
    "filter_new_tool_calls",
    "current_model_token_usage",
    "current_model_cost_usage",
    "tool_call_signature",
]
