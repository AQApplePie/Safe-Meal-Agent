"""工具执行节点。

该节点只执行工具注册表中的已授权工具，不做业务判断，保证工具执行和答案推理
职责分离。
"""

from safemeal.application.agent.tools.policy import review_tool_calls
from safemeal.application.contracts.agent.context import AgentContext

from safemeal.application.contracts.agent.state import AgentState, AgentStateUpdate
from safemeal.application.ports.tools.tool_executor import ToolExecutor
from safemeal.application.agent.utils.loop_control import tool_call_signature


def create_executor_node(tool_executor: ToolExecutor):
    async def execute_tools(state: AgentState) -> AgentStateUpdate:
        calls, rejected = review_tool_calls(
            state.get("pending_calls", []),
            state.get("dietary_constraints"),
            requirements=AgentContext.model_validate(
                state.get("agent_context") or {}
            ).requirements,
        )
        results = [*rejected, *await tool_executor.invoke_many(calls)]
        output: AgentStateUpdate = {
            "tool_results": results,
            "iteration": state.get("iteration", 0) + 1,
            "tool_call_count": state.get("tool_call_count", 0) + len(calls),
            "executed_call_signatures": [
                *state.get("executed_call_signatures", []),
                *(tool_call_signature(call) for call in calls),
            ],
        }
        return output

    return execute_tools
