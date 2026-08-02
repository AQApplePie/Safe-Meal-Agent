from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage, AIMessageChunk
import pytest

from safemeal.application.agents.models import PlanDecision
from safemeal.application.errors import PartialStreamInterruptedError
from safemeal.application.observability import use_answer_stream
from safemeal.config import settings
from safemeal.infrastructure.llm.decision_engine import OpenAIDecisionEngine
from safemeal.infrastructure.llm.provider_router import (
    LLMProvider,
    LLMProviderRouter,
    ProviderRouteExhausted,
)


def test_single_provider_router_returns_result() -> None:
    provider = LLMProvider("primary", "model", "http://provider", "key")
    router: LLMProviderRouter[str] = LLMProviderRouter([provider])

    async def operation(selected: LLMProvider) -> str:
        return selected.model

    assert asyncio.run(router.execute(operation)) == "model"


def test_single_provider_router_wraps_retryable_failure() -> None:
    provider = LLMProvider("primary", "model", "http://provider", "key")
    router: LLMProviderRouter[str] = LLMProviderRouter([provider])

    async def operation(_: LLMProvider) -> str:
        raise TimeoutError("timeout")

    with pytest.raises(ProviderRouteExhausted, match="TimeoutError"):
        asyncio.run(
            router.execute(
                operation, is_retryable=lambda exc: isinstance(exc, TimeoutError)
            )
        )


def test_router_rejects_multiple_providers() -> None:
    providers = [
        LLMProvider("primary", "model", "http://provider", "key"),
        LLMProvider("fallback", "model", "http://fallback", "key"),
    ]
    with pytest.raises(ValueError, match="exactly one"):
        LLMProviderRouter(providers)


class _StreamingModel:
    def __init__(self, chunks: list[str], error: Exception | None = None) -> None:
        self.chunks = chunks
        self.error = error

    async def astream(self, messages: object):
        for chunk in self.chunks:
            yield AIMessageChunk(content=chunk)
        if self.error is not None:
            raise self.error


def test_stream_preserves_visible_text_before_interruption() -> None:
    engine = OpenAIDecisionEngine(
        model="test-primary",
        api_key="test-key",
        base_url="http://primary.invalid/v1",
        max_retries=0,
    )
    model = _StreamingModel(["已生成内容"], TimeoutError("stream interrupted"))
    engine._model = lambda temperature=0.0, provider=None: model  # type: ignore[method-assign]

    async def scenario() -> list[str]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        with use_answer_stream(queue):
            with pytest.raises(PartialStreamInterruptedError):
                await engine.answer("问题", [], [], "", True, [])
        return [queue.get_nowait() for _ in range(queue.qsize())]

    assert asyncio.run(scenario()) == ["已生成内容"]


def test_structured_output_validation_is_repaired_once(monkeypatch) -> None:
    monkeypatch.setattr(settings, "LLM_STRUCTURED_REPAIR_RETRIES", 1)
    engine = OpenAIDecisionEngine(
        model="test-primary",
        api_key="test-key",
        base_url="http://primary.invalid/v1",
        max_retries=0,
    )

    class StructuredModel:
        calls = 0

        async def ainvoke(self, messages: object):
            self.calls += 1
            if self.calls == 1:
                return {
                    "raw": AIMessage(content="{}"),
                    "parsed": None,
                    "parsing_error": ValueError("missing decision"),
                }
            return {
                "raw": AIMessage(content='{"decision":"answer"}'),
                "parsed": PlanDecision(
                    decision="answer",
                    rationale="repaired",
                    direct_answer="你好",
                ),
                "parsing_error": None,
            }

    class Model:
        structured = StructuredModel()

        def with_structured_output(self, schema: object, include_raw: bool = False):
            assert include_raw is True
            return self.structured

    model = Model()
    engine._model = lambda temperature=0.0, provider=None: model  # type: ignore[method-assign]

    decision = asyncio.run(engine.plan("你好", [], [], []))

    assert decision.direct_answer == "你好"
    assert model.structured.calls == 2
