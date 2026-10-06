"""统计单次请求中的模型令牌与费用预算。"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Mapping
import json

from safemeal.application.contracts.agent.budget import ModelPrice, TokenUsage


def parse_model_pricing(raw: str) -> dict[str, ModelPrice]:
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise ValueError("MODEL_PRICING_JSON must be an object")
    prices = {}
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


class ModelBudget:

    def __init__(self, pricing: Mapping[str, ModelPrice]):
        self.pricing = pricing
        self.tokens = 0
        self.cost = 0.0
        self.calls = 0
        self.priced_calls = 0

    def charge(self, model: str, response: object) -> None:
        usage, available = extract_token_usage(response)
        self.tokens += usage.total_tokens
        self.calls += 1
        price = self.pricing.get(model) or self.pricing.get("*")
        if price is None or not available:
            return
        cached = min(usage.cached_tokens, usage.input_tokens)
        self.cost += (
            (usage.input_tokens - cached) * price.input_cost_per_million
            + cached * price.cached_input_cost_per_million
            + usage.output_tokens * price.output_cost_per_million
        ) / 1_000_000
        self.priced_calls += 1


_CURRENT_BUDGET: ContextVar[ModelBudget | None] = ContextVar(
    "model_budget", default=None
)


@contextmanager
def use_model_budget(pricing: Mapping[str, ModelPrice]) -> Iterator[ModelBudget]:
    budget = ModelBudget(pricing)
    token = _CURRENT_BUDGET.set(budget)
    try:
        yield budget
    finally:
        _CURRENT_BUDGET.reset(token)


def charge_model_usage(model: str, response: object) -> None:
    budget = _CURRENT_BUDGET.get()
    if budget is not None:
        budget.charge(model, response)


def current_model_token_usage() -> int:
    budget = _CURRENT_BUDGET.get()
    return budget.tokens if budget else 0


def current_model_cost_usage() -> tuple[float, bool]:
    budget = _CURRENT_BUDGET.get()
    if budget is None:
        return 0.0, False
    return budget.cost, budget.calls > 0 and budget.calls == budget.priced_calls


def extract_token_usage(response: object) -> tuple[TokenUsage, bool]:
    """从 LangChain AIMessage 中提取供应商 Token usage。

    Args:
        response: 原始模型响应对象。
    """

    if response is None:
        return TokenUsage(), False

    usage_payload = getattr(response, "usage_metadata", None)
    usage = usage_payload if isinstance(usage_payload, dict) else {}
    response_metadata_payload = getattr(response, "response_metadata", None)
    response_metadata = (
        response_metadata_payload if isinstance(response_metadata_payload, dict) else {}
    )
    token_usage_payload = (
        response_metadata.get("token_usage") or response_metadata.get("usage") or {}
    )
    token_usage = token_usage_payload if isinstance(token_usage_payload, dict) else {}
    input_tokens = int(
        usage.get("input_tokens")
        or token_usage.get("prompt_tokens")
        or token_usage.get("input_tokens")
        or 0
    )
    output_tokens = int(
        usage.get("output_tokens")
        or token_usage.get("completion_tokens")
        or token_usage.get("output_tokens")
        or 0
    )
    total_tokens = int(
        usage.get("total_tokens")
        or token_usage.get("total_tokens")
        or input_tokens + output_tokens
    )
    input_details = usage.get("input_token_details") or {}
    cached_tokens = int(
        input_details.get("cache_read") or token_usage.get("cached_tokens") or 0
    )
    return (
        TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_tokens=cached_tokens,
        ),
        bool(usage or token_usage),
    )
