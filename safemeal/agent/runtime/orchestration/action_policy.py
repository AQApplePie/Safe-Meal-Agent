"""统一校验 Planner 与 Reflector 提议的工具行动。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from safemeal.agent.contracts.decisions import ModelBudgetUsage, ToolCall
from safemeal.agent.contracts.state import AgentState
from safemeal.agent.runtime.orchestration.loop_control import filter_new_tool_calls
from safemeal.agent.runtime.tools.contracts.base import ToolSpecification


# 类说明（数据契约类）：ActionPolicyDecision
# 作用：行动策略校验后的唯一结果。
@dataclass(frozen=True)
class ActionPolicyDecision:
    """行动策略校验后的唯一结果。"""

    # 字段说明：calls
    # 作用：待执行或待审核的工具调用列表。
    # 类型：list[ToolCall]。
    calls: list[ToolCall]
    # 字段说明：budget_exhausted
    # 作用：本轮令牌、成本、工具次数或执行时间预算是否已耗尽。
    # 类型：bool。
    # 初始值：False。
    budget_exhausted: bool = False
    # 字段说明：stop_reason
    # 作用：执行循环终止原因，用于解释预算、失败或任务完成等停止条件。
    # 类型：str。
    # 初始值：''。
    stop_reason: str = ""
    # 字段说明：duplicate_count
    # 作用：去重过程中识别的重复项数量。
    # 类型：int。
    # 初始值：0。
    duplicate_count: int = 0
    # 字段说明：invalid_count
    # 作用：输入、候选或事件中不符合校验要求的数量。
    # 类型：int。
    # 初始值：0。
    invalid_count: int = 0


# 方法说明：validate_tool_actions
# 作用：统一执行工具存在性、调用预算、重复调用与模型预算校验。
# 入参：
#   state（AgentState）：Agent 完整图状态。
#   calls（Sequence[ToolCall]）：待执行或待审核的工具调用列表。
#   tool_specs（Sequence[ToolSpecification]）：工具用途与参数规范集合。
#   model_budget（ModelBudgetUsage | None）：本轮模型或执行预算；默认值为 None。
# 出参：ActionPolicyDecision；确定性动作策略决策。
def validate_tool_actions(
    *,
    state: AgentState,
    calls: Sequence[ToolCall],
    tool_specs: Sequence[ToolSpecification],
    model_budget: ModelBudgetUsage | None = None,
) -> ActionPolicyDecision:
    """统一执行工具存在性、调用预算、重复调用与模型预算校验。"""

    available_tools = {spec.name for spec in tool_specs}
    legal_calls = [call for call in calls if call.tool_name in available_tools]
    invalid_count = len(calls) - len(legal_calls)

    remaining_calls = max(
        0,
        state.get("max_tool_calls", 12) - state.get("tool_call_count", 0),
    )
    accepted, duplicate_count = filter_new_tool_calls(
        legal_calls,
        executed_signatures=state.get("executed_call_signatures", []),
        remaining_calls=remaining_calls,
        tool_trace=state.get("tool_trace", []),
    )

    token_exhausted = False
    cost_exhausted = False
    cost_unavailable = False
    if model_budget is not None:
        token_exhausted = model_budget.tokens >= state.get("max_model_tokens", 20_000)
        max_cost = state.get("max_model_cost", 0.0)
        cost_exhausted = bool(
            max_cost > 0
            and model_budget.cost_complete
            and model_budget.cost >= max_cost
        )
        cost_unavailable = bool(max_cost > 0 and not model_budget.cost_complete)

    if token_exhausted or cost_exhausted or cost_unavailable:
        accepted = []

    budget_exhausted = bool(
        remaining_calls <= 0 or token_exhausted or cost_exhausted or cost_unavailable
    )
    stop_reason = (
        "model_token_budget"
        if token_exhausted
        else "model_cost_budget"
        if cost_exhausted
        else "model_cost_unavailable"
        if cost_unavailable
        else "tool_call_budget"
        if remaining_calls <= 0
        else "invalid_tool_action"
        if invalid_count and not accepted
        else "duplicate_tool_call"
        if duplicate_count and not accepted
        else ""
    )
    return ActionPolicyDecision(
        calls=accepted,
        budget_exhausted=budget_exhausted,
        stop_reason=stop_reason,
        duplicate_count=duplicate_count,
        invalid_count=invalid_count,
    )


__all__ = ["ActionPolicyDecision", "validate_tool_actions"]
