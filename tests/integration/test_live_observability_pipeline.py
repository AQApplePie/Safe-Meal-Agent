from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from prometheus_client import generate_latest

from SafeMealAgent.back.bootstrap.container import AppContainer


def test_live_agent_queue_cost_trace_decision_and_metrics_pipeline() -> None:
    if os.getenv("RUN_OBSERVABILITY_INTEGRATION") != "1":
        pytest.skip(
            "set RUN_OBSERVABILITY_INTEGRATION=1 to run the paid observability test"
        )

    async def scenario() -> tuple[dict, list[dict]]:
        container = AppContainer()
        session_id = f"observability-{uuid4().hex}"
        try:
            response = await container.get_agent_graph_runner_service().process(
                "请直接用一句话回答：你好",
                session_id,
                include_trace=True,
            )
            trace = response.metadata["trace"]
            records = await asyncio.to_thread(
                container.trace_store.list_records,
                run_id=trace["run_id"],
                decisions_only=True,
            )
            return trace, records
        finally:
            await container.shutdown()

    trace, records = asyncio.run(scenario())

    assert trace["status"] == "ok"
    assert trace["metadata"]["queue_wait_ms"] >= 0
    assert trace["token_usage_complete"] is True
    assert trace["token_usage"]["total_tokens"] > 0
    assert trace["cost_usage_complete"] is True
    assert trace["cost_usage"]["currency"] == "CNY"
    assert trace["cost_usage"]["total_cost"] > 0
    assert len(records) == 1
    assert records[0]["decisions"]
    metrics = generate_latest().decode()
    assert 'safemeal_agent_runs_total{status="ok"}' in metrics
    assert (
        'safemeal_model_calls_total{model="qwen3-max",stage="planner",status="ok"}'
        in metrics
    )
