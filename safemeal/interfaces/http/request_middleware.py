"""实现 HTTP 接口层的请求与响应适配。"""

from __future__ import annotations

from uuid import uuid4
import re

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.responses import JSONResponse
from safemeal.bootstrap.composition.operations import create_rate_limiter


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):

    def __init__(self, app, *, max_bytes: int) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

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


class RedisTokenBucketMiddleware(BaseHTTPMiddleware):

    _EXEMPT_PATHS = {"/health", "/livez", "/readyz"}

    def __init__(self, app, *, redis_url: str, requests_per_minute: int) -> None:
        super().__init__(app)
        self._limit = requests_per_minute
        self._bucket = create_rate_limiter(redis_url)

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in self._EXEMPT_PATHS:
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        decision = await self._bucket.acquire(
            client,
            capacity=self._limit,
            refill_per_second=self._limit / 60,
        )
        if not decision.allowed:
            retry_seconds = max(1, (decision.retry_after_ms + 999) // 1000)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
                headers={"Retry-After": str(retry_seconds)},
            )
        return await call_next(request)


class RequestIdentityMiddleware(BaseHTTPMiddleware):

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
