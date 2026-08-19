from __future__ import annotations

import pytest

from safemeal.application.agent.execution_service import AgentExecutionService
from safemeal.application.contracts.agent_decisions import ToolCall


class InterruptedGraph:
    async def ainvoke(self, input_state, config=None):
        return {
            "pending_calls": [
                ToolCall(
                    id="generate-1",
                    tool_name="generate_recipe",
                    arguments={"dish_name": "测试菜"},
                    purpose="生成候选",
                    success_criteria="返回强类型菜谱",
                )
            ]
        }


@pytest.mark.graph
async def test_interrupted_execution_is_not_reported_as_failure() -> None:
    service = AgentExecutionService(InterruptedGraph(), timeout_seconds=1)

    response = await service.process("生成一道菜", "tenant:user:session")

    assert response.status == "degraded"
    assert response.route == "human_approval"
    assert response.error_code == "human_approval_required"
