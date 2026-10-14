"""HTTP observation after routing; template labels and protected scrape endpoint."""

from hmac import compare_digest
from time import perf_counter
from fastapi import FastAPI, Request
from fastapi.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send, Message
from safemeal.config.platform import PlatformSettings
from safemeal.shared.contracts.observability import HttpMetricsSink
from safemeal.bootstrap.composition.operations import create_runtime_metrics


# 类说明（业务或基础设施实现类）：HttpMetricsMiddleware
# 作用：实现HTTP 请求指标中间件，封装该组件的业务处理与依赖协作。
class HttpMetricsMiddleware:
    # 方法说明：__init__
    # 作用：初始化HTTP 请求指标中间件，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   app（ASGIApp）：当前 FastAPI 或 ASGI 应用。
    #   metrics（HttpMetricsSink）：运行指标收集组件。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, app: ASGIApp, *, metrics: HttpMetricsSink) -> None:
        self.app, self.metrics = app, metrics

    # 方法说明：__call__
    # 作用：执行HTTP 请求指标中间件的可调用入口，处理传入请求或状态。
    # 入参：
    #   scope（Scope）：当前请求或查询的可信范围。
    #   receive（Receive）：ASGI 请求体接收回调。
    #   send（Send）：ASGI 响应发送回调。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") == "/metrics":
            await self.app(scope, receive, send)
            return
        status = 500
        started = perf_counter()

        # 方法说明：observed_send
        # 作用：包装 ASGI 响应发送，记录状态码等请求指标。
        # 入参：
        #   message（Message）：本轮用户消息或问题文本。
        # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
        async def observed_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, observed_send)
        finally:
            route = getattr(scope.get("route"), "path", "__unmatched__")
            method = scope.get("method", "OTHER")
            if method not in (
                "GET",
                "POST",
                "PUT",
                "DELETE",
                "PATCH",
                "OPTIONS",
                "HEAD",
            ):
                method = "OTHER"
            self.metrics.http(method, route, status, perf_counter() - started)


# 方法说明：configure_metrics
# 作用：绑定当前进程的运行指标收集器。
# 入参：
#   application（FastAPI）：当前 FastAPI 或 ASGI 应用。
#   config（PlatformSettings）：图调用或检查点配置。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def configure_metrics(application: FastAPI, config: PlatformSettings) -> None:
    if not config.METRICS_ENABLED:
        return
    container = getattr(application.state, "container", None)
    metrics = getattr(container, "metrics", None) or create_runtime_metrics()
    application.state.metrics = metrics
    application.add_middleware(HttpMetricsMiddleware, metrics=metrics)

    # 方法说明：scrape
    # 作用：校验指标访问凭据后返回 Prometheus 格式的运行指标。
    # 入参：
    #   request（Request）：HTTP 请求或应用层请求契约。
    # 出参：Response；HTTP 响应。
    @application.get("/metrics", include_in_schema=False)
    async def scrape(request: Request) -> Response:
        if config.METRICS_TOKEN and not compare_digest(
            request.headers.get("authorization", "").encode("utf-8"),
            ("Bearer " + config.METRICS_TOKEN).encode("utf-8"),
        ):
            return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
        collector = getattr(container, "get_outbox_metrics", None)
        snapshot = (
            await collector() if collector else {"enabled": 0.0, "collector_up": 0.0}
        )
        return Response(
            metrics.render(snapshot),
            media_type="text/plain; version=0.0.4",
            headers={"Cache-Control": "no-store"},
        )
