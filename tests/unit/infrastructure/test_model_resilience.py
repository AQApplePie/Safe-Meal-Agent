from __future__ import annotations

import asyncio
import os

from langchain_core.messages import AIMessage, AIMessageChunk
import pytest

from SafeMealAgent.back.application.errors import PartialStreamInterruptedError
from SafeMealAgent.back.application.observability import use_answer_stream
from back.config import settings
from SafeMealAgent.back.infrastructure.llm.decision_engine import OpenAIDecisionEngine
from SafeMealAgent.back.application.agents.models import PlanDecision
from SafeMealAgent.back.infrastructure.llm.provider_router import (
    LLMProvider,
    LLMProviderRouter,
)
from SafeMealAgent.back.infrastructure.operations.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)


def test_circuit_breaker_closed_open_half_open_closed() -> None:
    now = [0.0]
    breaker = CircuitBreaker(
        failure_threshold=2,
        recovery_timeout=5,
        clock=lambda: now[0],
    )

    breaker.acquire()
    breaker.record_failure()
    breaker.acquire()
    breaker.record_failure()
    assert breaker.state is CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        breaker.acquire()

    now[0] = 6
    assert breaker.state is CircuitState.HALF_OPEN
    breaker.acquire()
    with pytest.raises(CircuitOpenError, match="probe already in flight"):
        breaker.acquire()
    breaker.record_success()
    assert breaker.state is CircuitState.CLOSED


def test_router_uses_fallback_only_for_retryable_failures() -> None:
    providers = [
        LLMProvider("primary", "primary-model", "http://primary", "key"),
        LLMProvider("fallback", "fallback-model", "http://fallback", "key"),
    ]
    router: LLMProviderRouter[str] = LLMProviderRouter(providers)
    called: list[str] = []

    async def operation(provider: LLMProvider) -> str:
        called.append(provider.name)
        if provider.name == "primary":
            raise TimeoutError("primary timeout")
        return "fallback-answer"

    answer = asyncio.run(
        router.execute(
            operation, is_retryable=lambda exc: isinstance(exc, TimeoutError)
        )
    )
    assert answer == "fallback-answer"
    assert called == ["primary", "fallback"]


def test_router_rejects_duplicate_provider_names() -> None:
    provider = LLMProvider("same", "model", "http://provider", "key")
    with pytest.raises(ValueError, match="name must be unique"):
        LLMProviderRouter([provider, provider])


def test_deepseek_fallback_resolves_key_from_typed_settings(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "unit-test-deepseek-key")
    monkeypatch.setattr(
        settings,
        "LLM_FALLBACKS_JSON",
        '[{"name":"deepseekv4-pro","model":"deepseek-v4-pro",'
        '"base_url":"https://api.deepseek.com/v1",'
        '"api_key_env":"DEEPSEEK_API_KEY",'
        '"extra_body":{"thinking":{"type":"disabled"}}}]',
    )
    engine = OpenAIDecisionEngine(
        model="primary",
        api_key="primary-key",
        base_url="https://primary.invalid/v1",
    )

    fallback = engine.provider_router.providers[1]
    assert fallback.name == "deepseekv4-pro"
    assert fallback.model == "deepseek-v4-pro"
    assert fallback.api_key == "unit-test-deepseek-key"
    assert fallback.extra_body == {"thinking": {"type": "disabled"}}


class _StreamingModel:
    def __init__(self, chunks: list[str], error: Exception | None = None) -> None:
        self.chunks = chunks
        self.error = error
        self.called = False

    async def astream(self, messages: object):
        self.called = True
        for chunk in self.chunks:
            yield AIMessageChunk(content=chunk)
        if self.error is not None:
            raise self.error


def _streaming_engine(
    primary: _StreamingModel,
    fallback: _StreamingModel,
) -> OpenAIDecisionEngine:
    engine = OpenAIDecisionEngine(
        model="test-primary",
        api_key="test-key",
        base_url="http://primary.invalid/v1",
        max_retries=0,
    )
    engine.provider_router = LLMProviderRouter(
        [
            LLMProvider("primary", "test-primary", "http://primary", "key"),
            LLMProvider("fallback", "test-fallback", "http://fallback", "key"),
        ]
    )
    models = {"primary": primary, "fallback": fallback}
    engine._model = lambda temperature=0.0, provider=None: models[provider.name]  # type: ignore[method-assign,union-attr]
    return engine


def test_stream_does_not_mix_fallback_after_visible_primary_text() -> None:
    primary = _StreamingModel(["主模型残片"], TimeoutError("stream interrupted"))
    fallback = _StreamingModel(["备用模型完整答案"])
    engine = _streaming_engine(primary, fallback)

    async def scenario() -> list[str]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        with use_answer_stream(queue):
            with pytest.raises(PartialStreamInterruptedError):
                await engine.answer("问题", [], [], "", True, [])
        return [queue.get_nowait() for _ in range(queue.qsize())]

    assert asyncio.run(scenario()) == ["主模型残片"]
    assert not fallback.called


def test_stream_can_fallback_before_any_visible_text() -> None:
    primary = _StreamingModel([], TimeoutError("connect failed"))
    fallback = _StreamingModel(["备用模型完整答案"])
    engine = _streaming_engine(primary, fallback)

    async def scenario() -> tuple[str, list[str]]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        with use_answer_stream(queue):
            answer = await engine.answer("问题", [], [], "", True, [])
        chunks = [queue.get_nowait() for _ in range(queue.qsize())]
        return answer, chunks

    answer, chunks = asyncio.run(scenario())
    assert answer == "备用模型完整答案"
    assert chunks == ["备用模型完整答案"]
    assert fallback.called


def test_live_deepseek_fallback_when_real_key_is_configured() -> None:
    key = (settings.DEEPSEEK_API_KEY or os.getenv("DEEPSEEK_API_KEY") or "").strip()
    if not key or key.casefold().startswith(("replace-", "change-me", "your-")):
        pytest.skip(
            "set a real DEEPSEEK_API_KEY to run the live provider failover test"
        )

    engine = OpenAIDecisionEngine(
        model="forced-primary-failure",
        api_key="invalid-primary-key",
        base_url="http://127.0.0.1:1/v1",
        request_timeout=30,
        max_retries=0,
    )
    assert any(
        provider.name == "deepseekv4-pro"
        for provider in engine.provider_router.providers
    )

    decision = asyncio.run(engine.plan("请直接回答你好", [], [], []))
    assert decision is not None


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
