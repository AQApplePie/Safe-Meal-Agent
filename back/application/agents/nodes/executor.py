"""工具执行节点。

该节点只执行工具注册表中的已授权工具，不做业务判断，保证工具执行和答案推理
职责分离。
"""

from SafeMealAgent.back.application.observability import trace_span

from ..state import AgentState, AgentStateUpdate
from ..tool_registry import ToolRegistry
from ..loop_control import tool_call_signature


def create_executor_node(registry: ToolRegistry):
    async def execute_tools(state: AgentState) -> AgentStateUpdate:
        calls = state.get("pending_calls", [])
        with trace_span(
            "agent_node",
            "execute_tools",
            {
                "iteration": state.get("iteration", 0) + 1,
                "calls": [call.model_dump() for call in calls],
            },
        ) as span:
            results = await registry.invoke_many(calls)
            output: AgentStateUpdate = {
                "tool_results": results,
                "iteration": state.get("iteration", 0) + 1,
                "tool_call_count": state.get("tool_call_count", 0) + len(calls),
                "executed_call_signatures": [
                    *state.get("executed_call_signatures", []),
                    *(tool_call_signature(call) for call in calls),
                ],
            }
            span.set_output(output)
            return output

    return execute_tools
