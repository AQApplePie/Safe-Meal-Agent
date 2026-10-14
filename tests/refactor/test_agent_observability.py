import asyncio
from types import SimpleNamespace

import pytest

from safemeal.agent.runtime.budget import (
    charge_model_usage,
    extract_token_usage,
    parse_model_pricing,
    use_model_budget,
)
from safemeal.agent.runtime.observability import observe_request


@pytest.mark.parametrize("price", ["NaN", "Infinity", "-1"])
def test_invalid_prices_rejected(price):
    with pytest.raises(ValueError):
        parse_model_pricing('{"m":{"input_cost_per_million":' + price + "}}")


def test_total_only_is_counted_but_cost_unknown():
    with (
        observe_request() as observation,
        use_model_budget(
            parse_model_pricing('{"*":{"input_cost_per_million":2}}')
        ) as budget,
    ):
        charge_model_usage(
            "m", SimpleNamespace(usage_metadata={"total_tokens": 100}), outcome="error"
        )
    assert budget.tokens == 100
    snapshot = observation.snapshot()
    assert snapshot["estimated_cost"] is None
    assert snapshot["usage_complete"] is False
    assert snapshot["model_calls"][0]["outcome"] == "error"


@pytest.mark.parametrize(
    "details",
    [
        {"prompt_cache_hit_tokens": 20},
        {"prompt_tokens_details": {"cached_tokens": 20}},
    ],
)
def test_cache_discount_and_zero_output(details):
    response = SimpleNamespace(
        response_metadata={
            "token_usage": {"prompt_tokens": 100, "completion_tokens": 0, **details}
        }
    )
    with (
        observe_request() as observation,
        use_model_budget(
            parse_model_pricing(
                '{"m":{"input_cost_per_million":2,"cached_input_cost_per_million":1}}'
            )
        ),
    ):
        charge_model_usage("m", response, stage="answer", duration_ms=10)
    snapshot = observation.snapshot()
    assert snapshot["cached_input_tokens"] == 20
    assert snapshot["estimated_cost"] == pytest.approx(0.00018)
    assert snapshot["cost_complete"] is True


@pytest.mark.parametrize(
    "usage",
    [
        {"input_tokens": -1},
        {"input_tokens": float("nan")},
        {"input_tokens": "bad"},
        {"input_token_details": "bad"},
    ],
)
def test_malformed_metadata_does_not_mask_answer(usage):
    _, complete = extract_token_usage(SimpleNamespace(usage_metadata=usage))
    assert not complete


def test_request_context_isolation_and_reset():
    async def run(count):
        with observe_request() as observation, use_model_budget({}):
            for _ in range(count):
                await asyncio.sleep(0)
                charge_model_usage(
                    "m",
                    SimpleNamespace(
                        usage_metadata={"input_tokens": 2, "output_tokens": 1}
                    ),
                )
        return observation.snapshot()

    async def concurrent():
        return await asyncio.gather(run(1), run(3))

    first, second = asyncio.run(concurrent())
    assert first["total_tokens"] == 3
    assert second["total_tokens"] == 9
    with observe_request() as empty:
        assert empty.snapshot()["estimated_cost"] == 0
        assert empty.snapshot()["model_call_count"] == 0


def test_workflow_run_and_resume_attach_fresh_observation():
    from safemeal.agent.contracts.api import AgentProcessResponse
    from safemeal.agent.contracts.workflow.models import WorkflowRequest
    from safemeal.agent.workflow.runner import ChatWorkflow

    class Graph:
        async def ainvoke(self, state):
            charge_model_usage(
                "m",
                SimpleNamespace(usage_metadata={"input_tokens": 2, "output_tokens": 1}),
            )
            return {"result": AgentProcessResponse(message="ok", session_id="test")}

    async def run():
        workflow = ChatWorkflow(Graph(), Graph())
        first = await workflow.run(
            WorkflowRequest(message="test", user_id="test", session_id="test")
        )
        second = await workflow.resume("test", approved=True)
        return first, second

    for response in asyncio.run(run()):
        assert response.metadata["observability"]["model_call_count"] == 1
        assert response.metadata["observability"]["total_tokens"] == 3
        assert response.metadata["observability"]["estimated_cost"] is None
