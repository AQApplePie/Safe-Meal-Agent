"""Single-provider model invocation boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Generic, Sequence, TypeVar

from safemeal.shared.types import JsonObject

T = TypeVar("T")


@dataclass(frozen=True)
class LLMProvider:
    name: str
    model: str
    base_url: str
    api_key: str = field(repr=False)
    extra_body: JsonObject | None = None


class ProviderRouteExhausted(RuntimeError):
    pass


class LLMProviderRouter(Generic[T]):
    """Keep one stable adapter boundary without fallback/circuit machinery."""

    def __init__(self, providers: Sequence[LLMProvider], **_: object) -> None:
        if len(providers) != 1:
            raise ValueError("single-host mode requires exactly one LLM provider")
        self.providers = tuple(providers)

    async def execute(
        self,
        operation: Callable[[LLMProvider], Awaitable[T]],
        *,
        is_retryable: Callable[[Exception], bool] | None = None,
    ) -> T:
        try:
            return await operation(self.providers[0])
        except Exception as exc:
            if is_retryable is not None and not is_retryable(exc):
                raise
            raise ProviderRouteExhausted(
                f"model provider failed: {type(exc).__name__}: {exc}"
            ) from exc

    async def close(self) -> None:
        return None


__all__ = ["LLMProvider", "LLMProviderRouter", "ProviderRouteExhausted"]
