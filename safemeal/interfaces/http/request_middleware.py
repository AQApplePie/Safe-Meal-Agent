"""HTTP request correlation, body limits and lightweight rate limiting."""

from __future__ import annotations

from time import perf_counter
from uuid import uuid4
import re

from fastapi import Request
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.responses import JSONResponse
from safemeal.application.service.composition.operations import create_rate_limiter
from safemeal.application.observability import use_request_id


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject declared request bodies that exceed the process safety limit."""

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
    """Optional Redis Token Bucket for HTTP requests."""

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


class RequestObservabilityMiddleware(BaseHTTPMiddleware):
    """Attach a correlation ID and record compact request logs."""

    async def dispatch(self, request: Request, call_next) -> Response:
        supplied_request_id = request.headers.get("X-Request-ID", "")[:128]
        request_id = (
            supplied_request_id
            if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", supplied_request_id)
            else uuid4().hex
        )
        request.state.request_id = request_id
        started = perf_counter()
        status_code = 500

        with use_request_id(request_id), logger.contextualize(request_id=request_id):
            logger.info(
                "http.request.start method={} path={}",
                request.method,
                request.url.path,
            )
            try:
                response = await call_next(request)
                status_code = response.status_code
                response.headers["X-Request-ID"] = request_id
                return response
            finally:
                elapsed = perf_counter() - started
                route = request.scope.get("route")
                route_path = getattr(route, "path", None) or "__unmatched__"
                logger.info(
                    "http.request.completed method={} route={} status={} "
                    "elapsed_ms={:.3f}",
                    request.method,
                    route_path,
                    status_code,
                    elapsed * 1000,
                )
