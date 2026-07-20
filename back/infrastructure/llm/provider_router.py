"""按优先级执行并在失败时切换 Provider。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Generic, Sequence, TypeVar

from SafeMealAgent.back.infrastructure.operations.rate_limit import RedisTokenBucket
from SafeMealAgent.back.infrastructure.operations.resilience import CircuitBreaker, CircuitOpenError
from SafeMealAgent.back.application.observability.metrics import CIRCUIT_EVENTS, RATE_LIMIT_DECISIONS
from SafeMealAgent.back.shared.types import JsonObject

T = TypeVar("T")


@dataclass(frozen=True)
class LLMProvider:
    name: str
    model: str
    base_url: str
    api_key: str = field(repr=False)
    extra_body: JsonObject | None = None


class ProviderRouteExhausted(RuntimeError):
    """所有可用模型均失败或处于熔断状态。"""


class LLMProviderRouter(Generic[T]):
    def __init__(
        self,
        providers: Sequence[LLMProvider],
        *,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
        distributed_limiter: RedisTokenBucket | None = None,
        rate_limit_per_minute: int = 120,
    ) -> None:
        if not providers:
            raise ValueError("至少需要一个 LLM provider")
        names = [provider.name for provider in providers]
        if len(names) != len(set(names)):
            raise ValueError("LLM provider name must be unique")
        self.providers = tuple(providers)
        self.breakers = {
            provider.name: CircuitBreaker(
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
            )
            for provider in self.providers
        }
        self.distributed_limiter = distributed_limiter
        self.rate_limit_per_minute = rate_limit_per_minute

    async def execute(
        self,
        operation: Callable[[LLMProvider], Awaitable[T]],
        *,
        is_retryable: Callable[[Exception], bool] | None = None,
    ) -> T:
        errors: list[str] = []
        for provider in self.providers:
            if self.distributed_limiter is not None:
                decision = await self.distributed_limiter.acquire(
                    provider.name,
                    capacity=self.rate_limit_per_minute,
                    refill_per_second=self.rate_limit_per_minute / 60,
                )
                if not decision.allowed:
                    RATE_LIMIT_DECISIONS.labels(layer="model", outcome="rejected").inc()
                    errors.append(
                        f"{provider.name}: rate limited for {decision.retry_after_ms}ms"
                    )
                    continue
                RATE_LIMIT_DECISIONS.labels(layer="model", outcome="allowed").inc()
            breaker = self.breakers[provider.name]
            try:
                breaker.acquire()
            except CircuitOpenError as exc:
                CIRCUIT_EVENTS.labels(provider=provider.name, event="open_skip").inc()
                errors.append(f"{provider.name}: {exc}")
                continue
            try:
                result = await operation(provider)
            except Exception as exc:
                breaker.record_failure()
                CIRCUIT_EVENTS.labels(provider=provider.name, event="failure").inc()
                if is_retryable is not None and not is_retryable(exc):
                    raise
                errors.append(f"{provider.name}: {type(exc).__name__}: {exc}")
                continue
            breaker.record_success()
            CIRCUIT_EVENTS.labels(provider=provider.name, event="success").inc()
            return result
        raise ProviderRouteExhausted("all providers unavailable; " + "; ".join(errors))

    async def close(self) -> None:
        if self.distributed_limiter is not None:
            await self.distributed_limiter.close()


__all__ = ["LLMProvider", "LLMProviderRouter", "ProviderRouteExhausted"]
