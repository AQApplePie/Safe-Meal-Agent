"""编排层用于阻止重复工具调用并执行预算约束的确定性规则。"""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Iterable, Sequence
from collections.abc import Mapping

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
    tool_trace: Sequence[Mapping[str, object]] = (),
) -> tuple[list[ToolCall], int]:
    seen = set(executed_signatures)
    accepted: list[ToolCall] = []
    duplicates = 0
    for call in calls:
        signature = tool_call_signature(call)
        repeated_outcome = False
        if len(tool_trace) >= 2:
            previous, latest = tool_trace[-2], tool_trace[-1]
            repeated_outcome = (
                previous.get("tool") == latest.get("tool") == call.tool_name
                and previous.get("args") == latest.get("args") == call.arguments
                and previous.get("status") == latest.get("status")
            )
        if repeated_outcome or (not tool_trace and signature in seen):
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
