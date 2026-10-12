"""实现语言模型基础设施适配。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Generic, Sequence, TypeVar

from safemeal.shared.types import JsonObject

T = TypeVar("T")


# 类说明（数据契约类）：LLMProvider
# 作用：描述语言模型供应商配置的结构、类型及可校验字段。
@dataclass(frozen=True)
class LLMProvider:
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 类型：str。
    name: str
    # 字段说明：model
    # 作用：当前调用使用的模型名称。
    # 类型：str。
    model: str
    # 字段说明：base_url
    # 作用：外部服务的基础地址。
    # 类型：str。
    base_url: str
    # 字段说明：api_key
    # 作用：调用外部供应商所需的 API 凭据。
    # 类型：str。
    api_key: str = field(repr=False)
    # 字段说明：extra_body
    # 作用：随模型请求传递的供应商扩展参数。
    # 类型：JsonObject | None。
    # 初始值：None。
    extra_body: JsonObject | None = None


# 类说明（异常类）：ProviderRouteExhaustedError
# 作用：表示模型供应商路由耗尽异常，供上层识别并映射错误响应。
class ProviderRouteExhaustedError(RuntimeError):
    pass


# 类说明（业务或基础设施实现类）：LLMProviderRouter
# 作用：实现按场景选择供应商的模型路由器，封装该组件的业务处理与依赖协作。
class LLMProviderRouter(Generic[T]):
    # 方法说明：__init__
    # 作用：初始化按场景选择供应商的模型路由器，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   providers（Sequence[LLMProvider]）：可选的外部模型供应商配置集合。
    #   **_（object）：按被包装方法签名传递的额外参数。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, providers: Sequence[LLMProvider], **_: object) -> None:
        if len(providers) != 1:
            raise ValueError("single-host mode requires exactly one LLM provider")
        # 实例属性说明：providers
        # 作用：可选的外部模型供应商配置集合。
        self.providers = tuple(providers)

    # 方法说明：execute
    # 作用：根据已校验的调用参数执行按场景选择供应商的模型路由器。
    # 入参：
    #   operation（Callable[[LLMProvider], Awaitable[T]]）：需要在完整数据库事务中执行的函数。
    #   is_retryable（Callable[[Exception], bool] | None）：判断异常是否可以安全重试的回调；默认值为
    # None。
    # 出参：T；由泛型调用约定决定的结果。
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
            raise ProviderRouteExhaustedError(
                f"model provider failed: {type(exc).__name__}: {exc}"
            ) from exc

    # 方法说明：close
    # 作用：关闭当前组件拥有的客户端或连接，释放外部资源。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    async def close(self) -> None:
        return None


__all__ = ["LLMProvider", "LLMProviderRouter", "ProviderRouteExhaustedError"]
