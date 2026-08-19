from __future__ import annotations

import pytest

from safemeal.application.agent.graph import build_agent_graph
from safemeal.application.contracts.agent_decisions import PlanDecision


class DirectGateway:
    async def plan(self, **_kwargs):
        return PlanDecision(
            decision="answer",
            rationale="无需工具",
            direct_answer="生熟砧板分开可降低交叉污染。",
        )

    async def answer(self, **_kwargs):
        raise AssertionError("direct answer should bypass model answer")


class NoTools:
    def specifications(self):
        return []

    async def invoke_many(self, calls):
        raise AssertionError(calls)


@pytest.mark.graph
async def test_graph_direct_answer_path() -> None:
    graph = build_agent_graph(model_gateway=DirectGateway(), tool_executor=NoTools())

    result = await graph.ainvoke(
        {
            "messages": [{"role": "user", "content": "砧板要分开吗？"}],
            "agent_context": {},
        }
    )

    assert result["messages"][-1].content == "生熟砧板分开可降低交叉污染。"
    assert result["iteration"] == 0
