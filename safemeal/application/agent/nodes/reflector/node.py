"""Reflection 节点。

基于当前 Observation 判断证据是否足够，决定结束、继续补查或重新规划。
"""

from safemeal.application.observability import trace_span
from .assessment import (
    deterministic_evidence_is_sufficient,
)

from safemeal.application.ports.llm.language_model_gateway import LanguageModelGateway
from safemeal.application.agent.utils.state import AgentState, AgentStateUpdate
from safemeal.application.ports.tools.tool_executor import ToolExecutor
from safemeal.application.agent.utils.loop_control import (
    filter_new_tool_calls,
    current_model_cost_usage,
    current_model_token_usage,
)


def create_reflector_node(
    model_gateway: LanguageModelGateway,
    tool_executor: ToolExecutor,
):
    async def reflect(state: AgentState) -> AgentStateUpdate:
        iteration = state.get("iteration", 0)
        max_iterations = state.get("max_iterations", 4)
        with trace_span(
            "agent_node",
            "reflect",
            {
                "iteration": iteration,
                "max_iterations": max_iterations,
                "observation_count": len(state.get("observations", [])),
            },
        ) as span:
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
                span.set_output(sufficient_output)
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
                span.set_output(continue_output)
                return continue_output

            remaining_calls = state.get("max_tool_calls", 12) - state.get(
                "tool_call_count", 0
            )
            token_exhausted = current_model_token_usage() >= state.get(
                "max_model_tokens", 20_000
            )
            current_cost, cost_complete = current_model_cost_usage()
            max_cost = state.get("max_model_cost", 0.0)
            cost_exhausted = bool(
                max_cost > 0 and cost_complete and current_cost >= max_cost
            )
            cost_unavailable = bool(max_cost > 0 and not cost_complete)
            if (
                remaining_calls <= 0
                or token_exhausted
                or cost_exhausted
                or cost_unavailable
            ):
                reason = (
                    "工具调用预算已耗尽"
                    if remaining_calls <= 0
                    else (
                        "模型Token预算已耗尽"
                        if token_exhausted
                        else (
                            "模型成本预算已耗尽"
                            if cost_exhausted
                            else "模型未返回可核验的成本数据"
                        )
                    )
                )
                post_budget_output: AgentStateUpdate = {
                    "reflection_rationale": reason + "，停止继续检索并返回已有证据。",
                    "evidence_sufficient": False,
                    "missing_information": [reason],
                    "route": "finish",
                    "pending_calls": [],
                    "budget_exhausted": True,
                    "loop_stop_reason": (
                        "tool_call_budget"
                        if remaining_calls <= 0
                        else (
                            "model_token_budget"
                            if token_exhausted
                            else (
                                "model_cost_budget"
                                if cost_exhausted
                                else "model_cost_unavailable"
                            )
                        )
                    ),
                }
                span.set_output(post_budget_output)
                return post_budget_output

            decision = await model_gateway.reflect(
                question=state["question"],
                conversation_history=state.get("conversation_history", []),
                tool_specs=tool_executor.specifications(),
                observations=state.get("observations", []),
                iteration=iteration,
            )
            post_tokens_exhausted = current_model_token_usage() >= state.get(
                "max_model_tokens", 20_000
            )
            post_cost, post_cost_complete = current_model_cost_usage()
            post_cost_exhausted = bool(
                max_cost > 0 and post_cost_complete and post_cost >= max_cost
            )
            post_cost_unavailable = bool(max_cost > 0 and not post_cost_complete)
            if post_tokens_exhausted or post_cost_exhausted or post_cost_unavailable:
                reason = (
                    "模型Token预算已耗尽"
                    if post_tokens_exhausted
                    else (
                        "模型成本预算已耗尽"
                        if post_cost_exhausted
                        else "模型未返回可核验的成本数据"
                    )
                )
                budget_output: AgentStateUpdate = {
                    "reflection_rationale": reason + "，使用已有证据生成确定性摘要。",
                    "evidence_sufficient": False,
                    "missing_information": [reason],
                    "route": "finish",
                    "pending_calls": [],
                    "budget_exhausted": True,
                    "loop_stop_reason": (
                        "model_token_budget"
                        if post_tokens_exhausted
                        else (
                            "model_cost_budget"
                            if post_cost_exhausted
                            else "model_cost_unavailable"
                        )
                    ),
                }
                span.set_output(budget_output)
                return budget_output
            next_calls, duplicate_count = filter_new_tool_calls(
                decision.next_calls,
                executed_signatures=state.get("executed_call_signatures", []),
                remaining_calls=remaining_calls,
            )
            repeated_only = decision.decision == "continue" and not next_calls
            output: AgentStateUpdate = {
                "reflection_rationale": decision.rationale,
                "evidence_sufficient": decision.evidence_sufficient
                and not repeated_only,
                "missing_information": [
                    *decision.missing_information,
                    *(
                        ["反思节点请求了已经执行过的相同工具和参数"]
                        if repeated_only
                        else []
                    ),
                ],
                "route": "finish" if repeated_only else decision.decision,
                "pending_calls": (
                    next_calls if decision.decision == "continue" else []
                ),
                "loop_stop_reason": (
                    "duplicate_tool_call" if duplicate_count and repeated_only else ""
                ),
            }
            span.set_output(output)
            return output

    return reflect
