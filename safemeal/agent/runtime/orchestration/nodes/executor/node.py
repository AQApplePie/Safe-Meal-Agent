"""工具执行节点。

该节点只执行工具注册表中的已授权工具，不做业务判断，保证工具执行和答案推理
职责分离。
"""

from safemeal.agent.runtime.tools.policy import review_tool_calls
from safemeal.agent.contracts.context import AgentContext

from safemeal.agent.contracts.state import AgentState, AgentStateUpdate
from safemeal.agent.runtime.tools.ports.tool_executor import ToolExecutor
from safemeal.agent.runtime.orchestration.loop_control import tool_call_signature
from safemeal.shared.types import to_json_object


def create_executor_node(tool_executor: ToolExecutor):
    async def execute_tools(state: AgentState) -> AgentStateUpdate:
        proposed_calls = list(state.get("pending_calls", []))
        proposed_by_id = {call.id: call for call in proposed_calls}
        calls, rejected = review_tool_calls(
            proposed_calls,
            state.get("dietary_constraints"),
            requirements=AgentContext.model_validate(
                state.get("agent_context") or {}
            ).requirements,
        )
        results = [*rejected, *await tool_executor.invoke_many(calls)]
        results_by_id = {result.call_id: result for result in results}
        trace = list(state.get("tool_trace", []))
        for call in calls:
            result = results_by_id.get(call.id)
            proposed = proposed_by_id.get(call.id, call)
            data = result.data if result is not None and isinstance(result.data, dict) else {}
            items = data.get("items", []) if isinstance(data, dict) else []
            item_rows = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
            trace.append(
                to_json_object(
                    {
                        "tool": call.tool_name,
                        "args": proposed.arguments,
                        "effective_args": call.arguments,
                        "status": data.get("status") if data else getattr(result, "status", "error"),
                        "result_count": len(items) if isinstance(items, list) else 0,
                        "result_names": [
                            str(item.get("name"))
                            for item in item_rows
                            if item.get("name")
                        ],
                        "result_categories": sorted(
                            {
                                str(category)
                                for item in item_rows
                                for category in item.get("categories", []) or []
                            }
                        ),
                    }
                )
            )
        output: AgentStateUpdate = {
            "tool_results": results,
            "iteration": state.get("iteration", 0) + 1,
            "tool_call_count": state.get("tool_call_count", 0) + len(calls),
            "executed_call_signatures": [
                *state.get("executed_call_signatures", []),
                *(tool_call_signature(call) for call in proposed_calls),
            ],
            "tool_trace": trace,
        }
        return output

    return execute_tools
