"""Request-local diagnostics; no prompts, credentials or user identifiers."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import perf_counter
from typing import Iterator, cast


# 类说明（数据契约类）：RequestObservation
# 作用：描述单请求模型与工具轨迹观测的结构、类型及可校验字段。
@dataclass
class RequestObservation:
    # 字段说明：started
    # 作用：后台任务或组件是否已经启动。
    # 类型：float。
    # 配置：默认值工厂（每次创建独立对象）=perf_counter。
    started: float = field(default_factory=perf_counter)
    # 字段说明：model_calls
    # 作用：本轮发生的模型调用次数。
    # 类型：list[dict[str, object]]。
    # 配置：默认值工厂（每次创建独立对象）=list。
    model_calls: list[dict[str, object]] = field(default_factory=list)

    # 方法说明：snapshot
    # 作用：读取单请求模型与工具轨迹观测当前可见的状态快照。
    # 入参：
    #   无显式入参。
    # 出参：dict[str, object]；文本字符串、由调用约定决定的数据对象组成的映射。
    def snapshot(self) -> dict[str, object]:
        complete = all(call["estimated_cost"] is not None for call in self.model_calls)
        return {
            "duration_ms": round((perf_counter() - self.started) * 1000, 3),
            "model_call_count": len(self.model_calls),
            "input_tokens": sum(
                cast(int, call["input_tokens"]) for call in self.model_calls
            ),
            "output_tokens": sum(
                cast(int, call["output_tokens"]) for call in self.model_calls
            ),
            "cached_input_tokens": sum(
                cast(int, call["cached_input_tokens"]) for call in self.model_calls
            ),
            "total_tokens": sum(
                cast(int, call["total_tokens"]) for call in self.model_calls
            ),
            "usage_complete": all(call["usage_complete"] for call in self.model_calls),
            "cost_complete": complete,
            "estimated_cost": sum(
                cast(float, call["estimated_cost"]) for call in self.model_calls
            )
            if complete
            else None,
            "cost_unit": "configured_price_unit",
            "model_calls": list(self.model_calls),
        }


_CURRENT: ContextVar[RequestObservation | None] = ContextVar(
    "request_observation", default=None
)


# 方法说明：observe_request
# 作用：绑定本次请求的轨迹收集上下文，退出时恢复原观测状态。
# 入参：
#   无显式入参。
# 出参：Iterator[RequestObservation]；请求观测上下文；进入 with 块时取得本轮轨迹收集器。
@contextmanager
def observe_request() -> Iterator[RequestObservation]:
    observation = RequestObservation()
    token = _CURRENT.set(observation)
    try:
        yield observation
    finally:
        _CURRENT.reset(token)


# 方法说明：record_model_call
# 作用：保存模型调用阶段、耗时和 Token 用量，供请求观测使用。
# 入参：
#   call（dict[str, object]）：单个结构化工具调用。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def record_model_call(call: dict[str, object]) -> None:
    observation = _CURRENT.get()
    if observation is not None:
        observation.model_calls.append(call)
