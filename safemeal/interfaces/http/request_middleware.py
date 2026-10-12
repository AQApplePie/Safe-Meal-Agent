"""实现 HTTP 接口层的请求与响应适配。"""

from __future__ import annotations

from uuid import uuid4
import re

from fastapi import Request
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.responses import JSONResponse
from safemeal.bootstrap.composition.operations import create_rate_limiter


# 类说明（业务或基础设施实现类）：RequestSizeLimitMiddleware
# 作用：实现HTTP 请求体大小限制中间件，封装该组件的业务处理与依赖协作。
class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    # 方法说明：__init__
    # 作用：初始化HTTP 请求体大小限制中间件，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   app（由调用契约决定）：当前 FastAPI 或 ASGI 应用。
    #   max_bytes（int）：允许读取或保存的最大字节数。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, app, *, max_bytes: int) -> None:
        super().__init__(app)
        # 实例属性说明：_max_bytes
        # 作用：允许读取或保存的最大字节数。
        self._max_bytes = max_bytes

    # 方法说明：dispatch
    # 作用：执行 HTTP 中间件逻辑并调用下一个处理器。
    # 入参：
    #   request（Request）：HTTP 请求或应用层请求契约。
    #   call_next（由调用契约决定）：HTTP 中间件的后续处理函数。
    # 出参：Response；HTTP 响应。
    async def dispatch(self, request: Request, call_next) -> Response:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                declared_size = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length header"},
                )
            if declared_size > self._max_bytes:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body is too large"},
                )
        return await call_next(request)


# 类说明（业务或基础设施实现类）：RedisTokenBucketMiddleware
# 作用：实现HTTP 令牌桶限流中间件，封装该组件的业务处理与依赖协作。
class RedisTokenBucketMiddleware(BaseHTTPMiddleware):
    # 字段说明：_EXEMPT_PATHS
    # 作用：EXEMPTPATHS，供该组件初始化及运行控制使用。
    # 初始值：{'/health', '/livez', '/readyz', '/metrics'}。
    _EXEMPT_PATHS = {"/health", "/livez", "/readyz", "/metrics"}

    # 方法说明：__init__
    # 作用：初始化HTTP 令牌桶限流中间件，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   app（由调用契约决定）：当前 FastAPI 或 ASGI 应用。
    #   redis_url（str）：Redis 连接地址。
    #   requests_per_minute（int）：每分钟允许请求的上限。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, app, *, redis_url: str, requests_per_minute: int) -> None:
        super().__init__(app)
        # 实例属性说明：_limit
        # 作用：本次查询或处理的最大条目数。
        self._limit = requests_per_minute
        # 实例属性说明：_bucket
        # 作用：限流计数桶。
        self._bucket = create_rate_limiter(redis_url)

    # 方法说明：__call__
    # 作用：执行HTTP 令牌桶限流中间件的可调用入口，处理传入请求或状态。
    # 入参：
    #   scope（由调用契约决定）：当前请求或查询的可信范围。
    #   receive（由调用契约决定）：ASGI 请求体接收回调。
    #   send（由调用契约决定）：ASGI 响应发送回调。
    # 出参：None；无返回值，结果通过状态更新或外部操作体现。
    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            try:
                await super().__call__(scope, receive, send)
            finally:
                await self._bucket.close()
        else:
            await super().__call__(scope, receive, send)

    # 方法说明：dispatch
    # 作用：执行 HTTP 中间件逻辑并调用下一个处理器。
    # 入参：
    #   request（Request）：HTTP 请求或应用层请求契约。
    #   call_next（由调用契约决定）：HTTP 中间件的后续处理函数。
    # 出参：Response；HTTP 响应。
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in self._EXEMPT_PATHS:
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        try:
            decision = await self._bucket.acquire(
                client,
                capacity=self._limit,
                refill_per_second=self._limit / 60,
            )
        except RedisError:
            # Fail closed explicitly; health and protected metrics remain reachable.
            return JSONResponse(
                status_code=503,
                content={"error": "rate_limiter_unavailable"},
                headers={"Retry-After": "1"},
            )
        if not decision.allowed:
            retry_seconds = max(1, (decision.retry_after_ms + 999) // 1000)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
                headers={"Retry-After": str(retry_seconds)},
            )
        return await call_next(request)


# 类说明（业务或基础设施实现类）：RequestIdentityMiddleware
# 作用：实现请求可信身份绑定中间件，封装该组件的业务处理与依赖协作。
class RequestIdentityMiddleware(BaseHTTPMiddleware):
    # 方法说明：dispatch
    # 作用：执行 HTTP 中间件逻辑并调用下一个处理器。
    # 入参：
    #   request（Request）：HTTP 请求或应用层请求契约。
    #   call_next（由调用契约决定）：HTTP 中间件的后续处理函数。
    # 出参：Response；HTTP 响应。
    async def dispatch(self, request: Request, call_next) -> Response:
        supplied = request.headers.get("X-Request-ID", "")[:128]
        request_id = (
            supplied
            if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", supplied)
            else uuid4().hex
        )
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
