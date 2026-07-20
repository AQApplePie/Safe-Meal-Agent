from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from langchain_core.messages import AIMessage
from prometheus_client import generate_latest

from SafeMealAgent.back.application.observability.cost import (
    estimate_trace_cost,
    parse_model_pricing,
)
from SafeMealAgent.back.application.observability.models import (
    AgentRunTrace,
    ModelCallTrace,
    TokenUsage,
)
from SafeMealAgent.back.application.observability import AgentTraceRecorder, use_trace
from SafeMealAgent.back.application.agents.models import PlanDecision, ToolCall
from SafeMealAgent.back.application.agents.nodes.planner import create_planner_node
from SafeMealAgent.back.application.use_cases.agent.graph_runner_service import (
    AgentGraphRunnerService,
)
from SafeMealAgent.back.infrastructure.operations.trace_store import JsonlAgentTraceStore


def _model_call(
    *, model: str = "priced-model", usage_available: bool = True
) -> ModelCallTrace:
    now = datetime.now(timezone.utc)
    return ModelCallTrace(
        stage="planner",
        model=model,
        temperature=0,
        started_at=now,
        finished_at=now,
        latency_ms=1,
        messages=[],
        response={"decision": "answer"},
        usage=TokenUsage(
            input_tokens=1_000,
            output_tokens=500,
            cached_tokens=200,
        ),
        usage_available=usage_available,
    )


def test_model_cost_uses_configured_currency_prices_and_cache_rate() -> None:
    pricing = parse_model_pricing(
        '{"priced-model":{"input_cost_per_million":2,'
        '"output_cost_per_million":10,"cached_input_cost_per_million":0.5}}'
    )
    trace = AgentRunTrace(session_id="s1", question="q")
    trace.model_calls.append(_model_call())

    cost = estimate_trace_cost(trace, pricing, currency="CNY")

    assert cost.complete
    assert cost.currency == "CNY"
    assert cost.input_cost == 0.0016
    assert cost.cached_input_cost == 0.0001
    assert cost.output_cost == 0.005
    assert cost.total_cost == 0.0067


def test_model_cost_marks_unpriced_or_missing_usage_incomplete() -> None:
    trace = AgentRunTrace(session_id="s1", question="q")
    trace.model_calls.extend(
        [_model_call(model="unknown"), _model_call(usage_available=False)]
    )

    cost = estimate_trace_cost(trace, parse_model_pricing("{}"))

    assert not cost.complete
    assert cost.priced_calls == 0
    assert cost.total_calls == 2


def test_trace_store_persists_success_and_exposes_compact_decision_audit(
    tmp_path,
) -> None:
    store = JsonlAgentTraceStore(
        tmp_path / "traces.jsonl", max_bytes=10_000, backup_count=2
    )
    store.record(
        {
            "run_id": "run-1",
            "session_id": "session-1",
            "status": "ok",
            "started_at": "2026-07-15T00:00:00Z",
            "finished_at": "2026-07-15T00:00:01Z",
            "total_latency_ms": 1000,
            "token_usage": {"total_tokens": 50},
            "cost_usage": {"currency": "CNY", "total_cost": 0.01},
            "cost_usage_complete": True,
            "spans": [
                {
                    "name": "planner",
                    "started_at": "2026-07-15T00:00:00Z",
                    "duration_ms": 10,
                    "status": "ok",
                    "output": {
                        "route": "tools",
                        "planning_rationale": "需要检索原文",
                        "pending_calls": [{"tool_name": "milvus_vector_search"}],
                    },
                }
            ],
        }
    )

    records = store.list_records(run_id="run-1", decisions_only=True)

    assert len(records) == 1
    assert records[0]["decisions"][0]["rationale"] == "需要检索原文"
    assert records[0]["decisions"][0]["pending_tools"] == ["milvus_vector_search"]
    assert (tmp_path / "traces.jsonl").stat().st_mode & 0o777 == 0o600
    assert "trace" not in records[0]


def test_graph_runner_persists_every_successful_trace_and_exports_metrics() -> None:
    class Graph:
        async def ainvoke(self, input_state: dict) -> dict:
            return {
                "messages": [AIMessage(content="完成")],
                "observations": [],
                "iteration": 0,
                "evidence_sufficient": True,
            }

    class Store:
        records: list[dict] = []

        def record(self, trace: dict) -> None:
            self.records.append(trace)

        def list_records(self, **kwargs: object) -> list[dict]:
            return self.records

    store = Store()
    service = AgentGraphRunnerService(
        Graph(),  # type: ignore[arg-type]
        trace_store=store,  # type: ignore[arg-type]
        model_name="test-model",
    )

    response = asyncio.run(service.process("你好", "s1", include_trace=True))

    assert response.status == "ok"
    assert len(store.records) == 1
    assert store.records[0]["status"] == "ok"
    assert response.metadata["trace"]["run_id"] == store.records[0]["run_id"]
    metrics = generate_latest().decode()
    assert "safemeal_agent_runs_total" in metrics
    assert "safemeal_model_calls_total" in metrics
    assert "safemeal_tool_calls_total" in metrics
    assert "safemeal_rate_limit_decisions_total" in metrics
    assert "safemeal_distributed_queue_wait_seconds" in metrics


def test_planner_stops_before_more_work_when_priced_run_budget_is_exhausted() -> None:
    class Engine:
        async def plan(self, **kwargs: object) -> PlanDecision:
            return PlanDecision(
                decision="tools",
                rationale="search",
                calls=[
                    ToolCall(
                        id="c1",
                        tool_name="search_recipes",
                        arguments={"query": "鱼"},
                        purpose="检索",
                        success_criteria="有结果",
                    )
                ],
            )

    class Registry:
        def specifications(self) -> list:
            return []

    recorder = AgentTraceRecorder(question="鱼", session_id="s1")
    recorder.append_model_call(_model_call(model="qwen3-max"))
    node = create_planner_node(
        Engine(),  # type: ignore[arg-type]
        Registry(),  # type: ignore[arg-type]
    )
    state = {
        "question": "鱼",
        "observations": [],
        "conversation_history": [],
        "tool_call_count": 0,
        "max_tool_calls": 12,
        "max_model_tokens": 20_000,
        "max_model_cost": 0.001,
    }

    with use_trace(recorder):
        result = asyncio.run(node(state))  # type: ignore[arg-type]

    assert result["pending_calls"] == []
    assert result["budget_exhausted"] is True
    assert result["loop_stop_reason"] == "model_cost_budget"
