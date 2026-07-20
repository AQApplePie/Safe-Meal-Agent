"""Provider-configurable model cost estimation without hard-coded prices."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping

from .models import AgentRunTrace, TokenUsage


@dataclass(frozen=True)
class ModelPrice:
    input_cost_per_million: float
    output_cost_per_million: float
    cached_input_cost_per_million: float


@dataclass(frozen=True)
class CostUsage:
    currency: str = "CNY"
    input_cost: float = 0.0
    output_cost: float = 0.0
    cached_input_cost: float = 0.0
    total_cost: float = 0.0
    priced_calls: int = 0
    total_calls: int = 0

    @property
    def complete(self) -> bool:
        return self.total_calls > 0 and self.priced_calls == self.total_calls


def parse_model_pricing(raw: str) -> dict[str, ModelPrice]:
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise ValueError("MODEL_PRICING_JSON must be an object")
    prices: dict[str, ModelPrice] = {}
    for model, item in payload.items():
        if not isinstance(item, dict):
            raise ValueError(f"pricing for {model!r} must be an object")
        input_price = float(item.get("input_cost_per_million", 0))
        output_price = float(item.get("output_cost_per_million", 0))
        cached_price = float(item.get("cached_input_cost_per_million", input_price))
        if min(input_price, output_price, cached_price) < 0:
            raise ValueError("model prices cannot be negative")
        prices[str(model)] = ModelPrice(input_price, output_price, cached_price)
    return prices


def estimate_call_cost(
    model: str,
    usage: TokenUsage,
    pricing: Mapping[str, ModelPrice],
) -> tuple[float, float, float] | None:
    price = pricing.get(model) or pricing.get("*")
    if price is None:
        return None
    cached = min(usage.cached_tokens, usage.input_tokens)
    uncached = max(0, usage.input_tokens - cached)
    input_cost = uncached * price.input_cost_per_million / 1_000_000
    cached_cost = cached * price.cached_input_cost_per_million / 1_000_000
    output_cost = usage.output_tokens * price.output_cost_per_million / 1_000_000
    return input_cost, output_cost, cached_cost


def estimate_trace_cost(
    trace: AgentRunTrace,
    pricing: Mapping[str, ModelPrice],
    *,
    currency: str = "CNY",
) -> CostUsage:
    input_cost = output_cost = cached_cost = 0.0
    priced = 0
    for call in trace.model_calls:
        estimated = estimate_call_cost(call.model, call.usage, pricing)
        if estimated is None or not call.usage_available:
            continue
        call_input, call_output, call_cached = estimated
        input_cost += call_input
        output_cost += call_output
        cached_cost += call_cached
        priced += 1
    return CostUsage(
        currency=currency,
        input_cost=round(input_cost, 8),
        output_cost=round(output_cost, 8),
        cached_input_cost=round(cached_cost, 8),
        total_cost=round(input_cost + output_cost + cached_cost, 8),
        priced_calls=priced,
        total_calls=len(trace.model_calls),
    )


__all__ = [
    "CostUsage",
    "ModelPrice",
    "estimate_call_cost",
    "estimate_trace_cost",
    "parse_model_pricing",
]
