"""编排层用于阻止重复工具调用并执行预算约束的确定性规则。"""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Iterable, Sequence
from collections.abc import Mapping

from safemeal.agent.runtime.budget import (
    current_model_token_usage,
    current_model_cost_usage,
)
from safemeal.agent.contracts.decisions import ToolCall


# 方法说明：tool_call_signature
# 作用：把工具名称和归一化参数编码为稳定签名。
# 入参：
#   call（ToolCall）：单个结构化工具调用。
# 出参：str；用于识别重复工具调用的稳定签名。
def tool_call_signature(call: ToolCall) -> str:
    payload = json.dumps(
        call.arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(f"{call.tool_name}:{payload}".encode("utf-8")).hexdigest()


# 方法说明：filter_new_tool_calls
# 作用：去除已执行签名对应的工具调用，防止无效重复循环。
# 入参：
#   calls（Sequence[ToolCall]）：待执行或待审核的工具调用列表。
#   executed_signatures（Iterable[str]）：已执行工具调用的稳定签名集合。
#   remaining_calls（int）：剩余允许执行的工具调用数。
#   tool_trace（Sequence[Mapping[str, object]]）：本轮已收集的工具调用轨迹；默认值为 ()。
# 出参：tuple[list[ToolCall], int]；待执行的结构化工具调用的集合、整数组成的元组。
def filter_new_tool_calls(
    calls: Sequence[ToolCall],
    *,
    executed_signatures: Iterable[str],
    remaining_calls: int,
    tool_trace: Sequence[Mapping[str, object]] = (),
) -> tuple[list[ToolCall], int]:
    executed = set(executed_signatures)
    accepted_signatures: set[str] = set()
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
        if (
            signature in accepted_signatures
            or repeated_outcome
            or (not tool_trace and signature in executed)
        ):
            duplicates += 1
            continue
        if len(accepted) >= max(0, remaining_calls):
            break
        accepted_signatures.add(signature)
        accepted.append(call)
    return accepted, duplicates


__all__ = [
    "filter_new_tool_calls",
    "current_model_token_usage",
    "current_model_cost_usage",
    "tool_call_signature",
]
