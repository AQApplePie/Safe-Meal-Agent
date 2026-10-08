"""Reflection 节点。

基于当前 Observation 判断证据是否足够，决定结束、继续补查或重新规划。
"""

from .assessment import (
    deterministic_evidence_is_sufficient,
    recommendation_completion,
)

from safemeal.agent.runtime.model import AgentModelGateway
from safemeal.agent.contracts.state import AgentState, AgentStateUpdate
from safemeal.agent.runtime.tools.ports.tool_executor import ToolExecutor
from safemeal.agent.runtime.orchestration.loop_control import (
    current_model_cost_usage,
    current_model_token_usage,
)
from safemeal.agent.runtime.orchestration.action_policy import validate_tool_actions
from safemeal.agent.contracts.decisions import ModelBudgetUsage
from safemeal.agent.contracts.menu_planning import MenuTaskProgress


def create_reflector_node(
    model_gateway: AgentModelGateway,
    tool_executor: ToolExecutor,
):
    async def reflect(state: AgentState) -> AgentStateUpdate:
        iteration = state.get("iteration", 0)
        max_iterations = state.get("max_iterations", 4)
        if state.get("menu_task_progress"):
            progress = MenuTaskProgress.model_validate(state["menu_task_progress"])
            if progress.complete:
                return {
                    "reflection_rationale": "所有菜单分类配额已经由确定性计数验证完成。",
                    "evidence_sufficient": True,
                    "missing_information": [],
                    "route": "finish",
                    "pending_calls": [],
                }
            unfinished = {
                category: count
                for category, count in progress.remaining.items()
                if count > 0
            }
            searchable = {
                category: count
                for category, count in unfinished.items()
                if category not in progress.exhausted_categories
            }
            if searchable and iteration < max_iterations:
                return {
                    "reflection_rationale": f"菜单仍有未满足配额：{searchable}，返回 Planner 继续批量检索。",
                    "evidence_sufficient": False,
                    "missing_information": [
                        f"{category} 仍缺 {count} 道"
                        for category, count in searchable.items()
                    ],
                    "route": "replan",
                    "pending_calls": [],
                }
            reason = (
                progress.partial_reason
                or "达到最大迭代次数，菜单仍有未满足的分类配额。"
            )
            return {
                "reflection_rationale": reason,
                "evidence_sufficient": False,
                "missing_information": [
                    f"{category} 仍缺 {count} 道"
                    for category, count in unfinished.items()
                ],
                "route": "finish",
                "pending_calls": [],
                "loop_stop_reason": (
                    "menu_sources_exhausted"
                    if not searchable
                    else "max_iterations"
                ),
            }
        counted = recommendation_completion(state.get("observations", []))
        if counted is not None:
            requested, fulfilled, complete = counted
            return {
                "reflection_rationale": (
                    f"普通推荐完成度由代码验证：{fulfilled}/{requested}。"
                ),
                "evidence_sufficient": complete,
                "missing_information": (
                    [] if complete else [f"请求 {requested} 道，当前仅找到 {fulfilled} 道"]
                ),
                "route": "finish",
                "pending_calls": [],
                "loop_stop_reason": "" if complete else "recommendation_partial",
            }
        if deterministic_evidence_is_sufficient(state.get("observations", [])):
            sufficient_output: AgentStateUpdate = {
                "reflection_rationale": (
                    "确定性工具已返回满足成功标准的可用证据，无需继续补查。"
                ),
                "evidence_sufficient": True,
                "missing_information": [],
                "route": "finish",
                "pending_calls": [],
            }
            return sufficient_output
        if iteration >= max_iterations:
            continue_output: AgentStateUpdate = {
                "reflection_rationale": "达到最大迭代次数，停止继续调用工具。",
                "evidence_sufficient": False,
                "missing_information": ["达到最大迭代次数，仍未确认所有证据充分"],
                "route": "finish",
                "pending_calls": [],
                "loop_stop_reason": "max_iterations",
            }
            return continue_output

        tool_specs = tool_executor.specifications()
        current_cost, cost_complete = current_model_cost_usage()
        preflight = validate_tool_actions(
            state=state,
            calls=[],
            tool_specs=tool_specs,
            model_budget=ModelBudgetUsage(
                tokens=current_model_token_usage(),
                cost=current_cost,
                cost_complete=cost_complete,
            ),
        )
        if preflight.budget_exhausted:
            reason = {
                "tool_call_budget": "工具调用预算已耗尽",
                "model_token_budget": "模型Token预算已耗尽",
                "model_cost_budget": "模型成本预算已耗尽",
                "model_cost_unavailable": "模型未返回可核验的成本数据",
            }.get(preflight.stop_reason, "执行预算已耗尽")
            post_budget_output: AgentStateUpdate = {
                "reflection_rationale": reason + "，停止继续检索并返回已有证据。",
                "evidence_sufficient": False,
                "missing_information": [reason],
                "route": "finish",
                "pending_calls": [],
                "budget_exhausted": True,
                "loop_stop_reason": preflight.stop_reason,
            }
            return post_budget_output

        decision = await model_gateway.reflect(
            question=state["question"],
            conversation_history=state.get("conversation_history", []),
            tool_specs=tool_specs,
            observations=state.get("observations", []),
            iteration=iteration,
        )
        post_cost, post_cost_complete = current_model_cost_usage()
        action_policy = validate_tool_actions(
            state=state,
            calls=(decision.next_calls if decision.decision == "continue" else []),
            tool_specs=tool_specs,
            model_budget=ModelBudgetUsage(
                tokens=current_model_token_usage(),
                cost=post_cost,
                cost_complete=post_cost_complete,
            ),
        )
        if action_policy.budget_exhausted:
            reason = {
                "tool_call_budget": "工具调用预算已耗尽",
                "model_token_budget": "模型Token预算已耗尽",
                "model_cost_budget": "模型成本预算已耗尽",
                "model_cost_unavailable": "模型未返回可核验的成本数据",
            }.get(action_policy.stop_reason, "执行预算已耗尽")
            budget_output: AgentStateUpdate = {
                "reflection_rationale": reason + "，使用已有证据生成确定性摘要。",
                "evidence_sufficient": False,
                "missing_information": [reason],
                "route": "finish",
                "pending_calls": [],
                "budget_exhausted": True,
                "loop_stop_reason": action_policy.stop_reason,
            }
            return budget_output
        next_calls = action_policy.calls
        repeated_only = decision.decision == "continue" and not next_calls
        output: AgentStateUpdate = {
            "reflection_rationale": decision.rationale,
            "evidence_sufficient": decision.evidence_sufficient and not repeated_only,
            "missing_information": [
                *decision.missing_information,
                *(
                    ["反思节点请求了已经执行过的相同工具和参数"]
                    if repeated_only
                    else []
                ),
            ],
            "route": "finish" if repeated_only else decision.decision,
            "pending_calls": (next_calls if decision.decision == "continue" else []),
            "loop_stop_reason": (
                action_policy.stop_reason if repeated_only else ""
            ),
        }
        return output

    return reflect
