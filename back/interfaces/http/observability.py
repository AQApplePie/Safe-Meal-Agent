"""HTTP request correlation and Prometheus instrumentation."""

from __future__ import annotations

from time import perf_counter
from collections import defaultdict, deque
import asyncio
from uuid import uuid4
import re

from fastapi import Request
from loguru import logger
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.responses import JSONResponse
from SafeMealAgent.back.infrastructure.operations.rate_limit import RedisTokenBucket
from SafeMealAgent.back.application.observability.metrics import RATE_LIMIT_DECISIONS
from SafeMealAgent.back.application.observability import use_request_id


HTTP_REQUESTS = Counter(
    "safemeal_http_requests_total",
    "Total HTTP requests.",
    ("method", "route", "status"),
)
HTTP_LATENCY = Histogram(
    "safemeal_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "route"),
)
AGENT_STREAM_TTFT = Histogram(
    "safemeal_agent_stream_time_to_first_answer_seconds",
    "Time until the first answer data packet is available.",
)
AGENT_STREAM_DEGRADES = Counter(
    "safemeal_agent_stream_degrades_total",
    "Streams that exceeded the first-answer packet deadline.",
)


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


class RequestRateLimitMiddleware(BaseHTTPMiddleware):
    """Process-local sliding-window limiter suitable for the monolith deployment."""

    _EXEMPT_PATHS = {"/health", "/livez", "/readyz", "/metrics"}

    def __init__(self, app, *, requests_per_minute: int) -> None:
        super().__init__(app)
        self._limit = requests_per_minute
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in self._EXEMPT_PATHS:
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        now = perf_counter()
        async with self._lock:
            bucket = self._requests[client]
            while bucket and now - bucket[0] >= 60.0:
                bucket.popleft()
            if len(bucket) >= self._limit:
                RATE_LIMIT_DECISIONS.labels(
                    layer="http-local", outcome="rejected"
                ).inc()
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests"},
                    headers={"Retry-After": "60"},
                )
            bucket.append(now)
            RATE_LIMIT_DECISIONS.labels(layer="http-local", outcome="allowed").inc()
            if len(self._requests) > 10_000:
                stale = [
                    key
                    for key, values in self._requests.items()
                    if not values or now - values[-1] >= 60.0
                ]
                for key in stale:
                    self._requests.pop(key, None)
        return await call_next(request)


class DistributedRequestRateLimitMiddleware(BaseHTTPMiddleware):
    """Redis-backed request limiter shared by all API workers."""

    _EXEMPT_PATHS = {"/health", "/livez", "/readyz", "/metrics"}

    def __init__(self, app, *, redis_url: str, requests_per_minute: int) -> None:
        super().__init__(app)
        self._limit = requests_per_minute
        self._bucket = RedisTokenBucket(redis_url, prefix="safemeal:http")

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
            RATE_LIMIT_DECISIONS.labels(
                layer="http-distributed", outcome="rejected"
            ).inc()
            retry_seconds = max(1, (decision.retry_after_ms + 999) // 1000)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
                headers={"Retry-After": str(retry_seconds)},
            )
        RATE_LIMIT_DECISIONS.labels(layer="http-distributed", outcome="allowed").inc()
        return await call_next(request)


class RequestObservabilityMiddleware(BaseHTTPMiddleware):
    """Attach a correlation ID and record request-level logs and metrics."""

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
                # Never use an unmatched raw URL as a Prometheus label. Attackers can
                # otherwise create an unbounded number of time series via random 404 paths.
                route_path = getattr(route, "path", None) or "__unmatched__"
                HTTP_REQUESTS.labels(
                    method=request.method,
                    route=route_path,
                    status=str(status_code),
                ).inc()
                HTTP_LATENCY.labels(
                    method=request.method,
                    route=route_path,
                ).observe(elapsed)
                logger.info(
                    "http.request.completed method={} route={} status={} "
                    "elapsed_ms={:.3f}",
                    request.method,
                    route_path,
                    status_code,
                    elapsed * 1000,
                )
