"""统计单次请求中的模型令牌与费用预算。"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Mapping
import json
import math

from safemeal.agent.runtime.observability import record_model_call

from safemeal.agent.contracts.budget import ModelPrice, TokenUsage


# 方法说明：parse_model_pricing
# 作用：解析模型价格配置，并验证价格字段完整性与数值。
# 入参：
#   raw（str）：尚未完成归一化的外部原始数据。
# 出参：dict[str, ModelPrice]；文本字符串、模型输入输出与缓存价格组成的映射。
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
        if any(
            not math.isfinite(value) or value < 0
            for value in (input_price, output_price, cached_price)
        ):
            raise ValueError("model prices cannot be negative")
        prices[str(model)] = ModelPrice(input_price, output_price, cached_price)
    return prices


# 类说明（业务或基础设施实现类）：ModelBudget
# 作用：实现模型 Token 与成本预算，封装该组件的业务处理与依赖协作。
class ModelBudget:
    # 方法说明：__init__
    # 作用：初始化模型 Token 与成本预算，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   pricing（Mapping[str, ModelPrice]）：模型输入输出及缓存用量的价格配置。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, pricing: Mapping[str, ModelPrice]):
        # 实例属性说明：pricing
        # 作用：模型输入输出及缓存用量的价格配置。
        self.pricing = pricing
        # 实例属性说明：tokens
        # 作用：本轮累计模型输入与输出令牌总数。
        # 初始值：0。
        self.tokens = 0
        # 实例属性说明：cost
        # 作用：已核算的模型调用费用，计价单位沿用配置中的价格表。
        # 初始值：0.0。
        self.cost = 0.0
        # 实例属性说明：calls
        # 作用：本轮累计语言模型调用次数，与工具调用次数分别统计。
        # 初始值：0。
        self.calls = 0
        # 实例属性说明：priced_calls
        # 作用：能够取得价格并核算费用的模型调用次数。
        # 初始值：0。
        self.priced_calls = 0

    # 方法说明：charge
    # 作用：累计本次模型调用的 Token；具备用量和价格时计算并累计成本。
    # 入参：
    #   model（str）：当前调用使用的模型名称。
    #   response（object）：底层客户端响应或最终业务响应。
    # 出参：float | None；本次模型调用成本；用量或价格不可用时为 None。
    def charge(self, model: str, response: object) -> float | None:
        usage, available = extract_token_usage(response)
        self.tokens += usage.total_tokens
        self.calls += 1
        price = self.pricing.get(model) or self.pricing.get("*")
        if price is None or not available:
            return None
        cached = min(usage.cached_tokens, usage.input_tokens)
        cost = (
            (usage.input_tokens - cached) * price.input_cost_per_million
            + cached * price.cached_input_cost_per_million
            + usage.output_tokens * price.output_cost_per_million
        ) / 1_000_000
        self.cost += cost
        self.priced_calls += 1
        return cost


_CURRENT_BUDGET: ContextVar[ModelBudget | None] = ContextVar(
    "model_budget", default=None
)


# 方法说明：use_model_budget
# 作用：绑定本次请求的模型预算上下文，并在结束后恢复原上下文。
# 入参：
#   pricing（Mapping[str, ModelPrice]）：模型输入输出及缓存用量的价格配置。
# 出参：Iterator[ModelBudget]；模型 Token 与成本预算的迭代器。
@contextmanager
def use_model_budget(pricing: Mapping[str, ModelPrice]) -> Iterator[ModelBudget]:
    budget = ModelBudget(pricing)
    token = _CURRENT_BUDGET.set(budget)
    try:
        yield budget
    finally:
        _CURRENT_BUDGET.reset(token)


# 方法说明：charge_model_usage
# 作用：向当前请求的预算上下文登记模型 Token 与成本用量。
# 入参：
#   model（str）：当前调用使用的模型名称。
#   response（object）：底层客户端响应或最终业务响应。
#   stage（str）：当前执行或模型调用阶段；默认值为 'unspecified'。
#   duration_ms（float）：本阶段耗时，单位毫秒；默认值为 0.0。
#   outcome（str）：本次事件或查询处理的结果类别；默认值为 'success'。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def charge_model_usage(
    model: str,
    response: object,
    *,
    stage: str = "unspecified",
    duration_ms: float = 0.0,
    outcome: str = "success",
) -> None:
    budget = _CURRENT_BUDGET.get()
    cost = budget.charge(model, response) if budget is not None else None
    usage, available = extract_token_usage(response)
    record_model_call(
        {
            "model": model,
            "stage": stage,
            "duration_ms": round(duration_ms, 3),
            "outcome": outcome,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
            "cached_input_tokens": usage.cached_tokens,
            "usage_complete": available,
            "estimated_cost": cost,
        }
    )


# 方法说明：current_model_token_usage
# 作用：读取本次请求已累计的模型 Token 用量。
# 入参：
#   无显式入参。
# 出参：int；本轮模型调用累计的 Token 总数。
def current_model_token_usage() -> int:
    budget = _CURRENT_BUDGET.get()
    return budget.tokens if budget else 0


# 方法说明：current_model_cost_usage
# 作用：读取本次请求已累计的模型成本用量。
# 入参：
#   无显式入参。
# 出参：tuple[float, bool]；累计模型成本与成本统计是否完整的二元组。
def current_model_cost_usage() -> tuple[float, bool]:
    budget = _CURRENT_BUDGET.get()
    if budget is None:
        return 0.0, False
    return budget.cost, budget.calls > 0 and budget.calls == budget.priced_calls


# 方法说明：extract_token_usage
# 作用：从 LangChain AIMessage 中提取供应商 Token usage。
# 入参：
#   response（object）：底层客户端响应或最终业务响应。
# 出参：tuple[TokenUsage, bool]；模型输入输出与缓存 Token 用量、布尔判定值组成的元组。
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

    # 方法说明：value
    # 作用：按优先级读取可用 Token 用量字段，同时报告是否取得真实用量。
    # 入参：
    #   *sources（tuple[dict, str]）：当前答案或上下文的证据来源集合。
    # 出参：tuple[int, bool]；读取到的用量数值及是否找到真实字段的标记。
    def value(*sources: tuple[dict, str]) -> tuple[int, bool]:
        for payload, key in sources:
            if key in payload and payload[key] is not None:
                candidate = payload[key]
                if isinstance(candidate, bool) or not isinstance(
                    candidate, (int, float)
                ):
                    return 0, False
                if (
                    not math.isfinite(candidate)
                    or candidate < 0
                    or int(candidate) != candidate
                ):
                    return 0, False
                return int(candidate), True
        return 0, False

    input_tokens, has_input = value(
        (usage, "input_tokens"),
        (token_usage, "prompt_tokens"),
        (token_usage, "input_tokens"),
    )
    output_tokens, has_output = value(
        (usage, "output_tokens"),
        (token_usage, "completion_tokens"),
        (token_usage, "output_tokens"),
    )
    total_tokens, has_total = value(
        (usage, "total_tokens"), (token_usage, "total_tokens")
    )
    if not has_total:
        total_tokens = input_tokens + output_tokens
    input_details = usage.get("input_token_details")
    input_details = input_details if isinstance(input_details, dict) else {}
    prompt_details = token_usage.get("prompt_tokens_details")
    prompt_details = prompt_details if isinstance(prompt_details, dict) else {}
    cached_tokens, _ = value(
        (input_details, "cache_read"),
        (token_usage, "prompt_cache_hit_tokens"),
        (prompt_details, "cached_tokens"),
        (token_usage, "cached_tokens"),
    )
    consistent = (
        has_input
        and has_output
        and total_tokens == input_tokens + output_tokens
        and cached_tokens <= input_tokens
    )
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_tokens=min(cached_tokens, input_tokens),
    ), consistent
