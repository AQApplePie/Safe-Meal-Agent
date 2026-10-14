"""HTTP telemetry sink; adapters depend on a contract, not its storage."""

from typing import Protocol


# 类说明（接口类）：HttpMetricsSink
# 作用：定义HTTP 请求观测接收器的能力契约，供应用层与具体实现解耦。
class HttpMetricsSink(Protocol):
    # 方法说明：http
    # 作用：登记 HTTP 方法、路由、状态码和处理耗时指标。
    # 入参：
    #   method（str）：HTTP 请求方法。
    #   route（str）：HTTP 路由模板或业务路由标识。
    #   status（int）：HTTP 状态码或业务状态。
    #   seconds（float）：当前操作耗时或持续时长，单位秒。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def http(self, method: str, route: str, status: int, seconds: float) -> None: ...

    # 方法说明：render
    # 作用：将HTTP 请求观测接收器的结构化内容渲染为文本。
    # 入参：
    #   outbox（dict[str, float]）：同事务行为事件持久化组件。
    # 出参：str；文本字符串。
    def render(self, outbox: dict[str, float]) -> str: ...
