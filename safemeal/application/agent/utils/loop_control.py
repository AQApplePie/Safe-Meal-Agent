"""Deterministic safeguards for Agent tools loops."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Iterable, Sequence

from safemeal.application.observability import current_trace
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


def current_model_token_usage() -> int:
    recorder = current_trace()
    return recorder.trace.token_usage.total_tokens if recorder is not None else 0


def current_model_cost_usage() -> tuple[float, bool]:
    recorder = current_trace()
    if recorder is None:
        return 0.0, False
    usage = recorder.cost_usage()
    return usage.total_cost, usage.complete


__all__ = [
    "filter_new_tool_calls",
    "current_model_token_usage",
    "current_model_cost_usage",
    "tool_call_signature",
]
