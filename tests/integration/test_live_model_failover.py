from __future__ import annotations

import asyncio
import os

import pytest

from SafeMealAgent.back.infrastructure.llm.decision_engine import OpenAIDecisionEngine
from SafeMealAgent.back.infrastructure.llm.provider_router import LLMProvider, LLMProviderRouter


def test_live_network_failure_switches_to_configured_deepseek_provider() -> None:
    if os.getenv("RUN_MODEL_FAILOVER_INTEGRATION") != "1":
        pytest.skip("set RUN_MODEL_FAILOVER_INTEGRATION=1 to run live model failover")
    engine = OpenAIDecisionEngine(
        model="forced-primary-failure",
        api_key="invalid-primary-key",
        base_url="http://127.0.0.1:1/v1",
        request_timeout=30,
        max_retries=0,
    )
    deepseek_providers = [
        provider
        for provider in engine.provider_router.providers
        if provider.name == "deepseekv4-pro"
    ]
    if not deepseek_providers:
        pytest.skip("a real configured deepseekv4-pro provider is required")

    engine.provider_router = LLMProviderRouter(
        (
            LLMProvider(
                "forced-primary-failure",
                "forced-primary-failure",
                "http://127.0.0.1:1/v1",
                "invalid-primary-key",
            ),
            *deepseek_providers,
        ),
        failure_threshold=1,
        recovery_timeout=30,
    )

    decision = asyncio.run(engine.plan("请直接回答：你好", [], [], []))
    assert decision is not None
    assert (
        engine.provider_router.breakers["forced-primary-failure"].state.value == "open"
    )
    assert engine.provider_router.breakers["deepseekv4-pro"].state.value == "closed"
