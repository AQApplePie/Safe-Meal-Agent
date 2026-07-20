"""Atomic Redis token bucket shared across API, tool and model workers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
import asyncio
from time import perf_counter
from typing import AsyncIterator
from uuid import uuid4

import redis.asyncio as redis

from SafeMealAgent.back.application.observability.metrics import (
    QUEUE_ACTIVE,
    QUEUE_DEPTH,
    QUEUE_WAIT,
    RATE_LIMIT_DECISIONS,
)

_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])
local now = redis.call('TIME')
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
local values = redis.call('HMGET', key, 'tokens', 'updated_ms')
local tokens = tonumber(values[1]) or capacity
local updated = tonumber(values[2]) or now_ms
tokens = math.min(capacity, tokens + math.max(0, now_ms - updated) * refill / 1000)
local allowed = 0
local retry_ms = 0
if tokens >= requested then
  tokens = tokens - requested
  allowed = 1
else
  retry_ms = math.ceil((requested - tokens) / refill * 1000)
end
redis.call('HMSET', key, 'tokens', tokens, 'updated_ms', now_ms)
redis.call('PEXPIRE', key, math.ceil(capacity / refill * 2000))
return {allowed, tostring(tokens), retry_ms}
"""

_QUEUE_ACQUIRE_LUA = """
local queue_key = KEYS[1]
local active_key = KEYS[2]
local sequence_key = KEYS[3]
local member = ARGV[1]
local max_active = tonumber(ARGV[2])
local lease_ms = tonumber(ARGV[3])
local now = redis.call('TIME')
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)

redis.call('ZREMRANGEBYSCORE', active_key, '-inf', now_ms)
if not redis.call('ZSCORE', queue_key, member) then
  local sequence = redis.call('INCR', sequence_key)
  redis.call('ZADD', queue_key, sequence, member)
end

local rank = redis.call('ZRANK', queue_key, member)
local active = redis.call('ZCARD', active_key)
if rank == 0 and active < max_active then
  redis.call('ZREM', queue_key, member)
  redis.call('ZADD', active_key, now_ms + lease_ms, member)
  redis.call('PEXPIRE', active_key, lease_ms * 2)
  redis.call('PEXPIRE', queue_key, lease_ms * 2)
  redis.call('PEXPIRE', sequence_key, lease_ms * 2)
  return {1, redis.call('ZCARD', queue_key), active + 1}
end
return {0, redis.call('ZCARD', queue_key), active}
"""

_QUEUE_RELEASE_LUA = """
redis.call('ZREM', KEYS[1], ARGV[1])
redis.call('ZREM', KEYS[2], ARGV[1])
return 1
"""


@dataclass(frozen=True)
class TokenBucketDecision:
    allowed: bool
    remaining: float
    retry_after_ms: int


@dataclass(frozen=True)
class QueueAdmission:
    member: str
    wait_ms: int
    queue_depth: int
    active_leases: int


class DistributedQueueTimeout(TimeoutError):
    """A caller could not obtain a distributed concurrency lease in time."""


class RedisTokenBucket:
    def __init__(self, url: str, *, prefix: str = "safemeal:rate") -> None:
        self.client = redis.from_url(url, decode_responses=True)
        self.prefix = prefix

    async def acquire(
        self,
        key: str,
        *,
        capacity: int,
        refill_per_second: float,
        tokens: int = 1,
    ) -> TokenBucketDecision:
        if capacity < 1 or refill_per_second <= 0 or tokens < 1:
            raise ValueError("token bucket values must be positive")
        result = await self.client.eval(
            _TOKEN_BUCKET_LUA,
            1,
            f"{self.prefix}:{key}",
            capacity,
            refill_per_second,
            tokens,
        )
        decision = TokenBucketDecision(
            bool(int(result[0])), float(result[1]), int(result[2])
        )
        return decision

    async def close(self) -> None:
        await self.client.aclose()


class RedisFairQueueLimiter:
    """FIFO distributed concurrency queue with expiring leases.

    Redis owns both queue order and active leases, so API workers on different
    processes share one admission boundary. Expiry prevents a crashed worker
    from permanently consuming capacity.
    """

    def __init__(self, url: str, *, prefix: str = "safemeal:queue") -> None:
        self.client = redis.from_url(url, decode_responses=True)
        self.prefix = prefix

    def _keys(self, queue: str) -> tuple[str, str, str]:
        base = f"{self.prefix}:{queue}"
        return f"{base}:waiting", f"{base}:active", f"{base}:sequence"

    async def acquire(
        self,
        queue: str,
        *,
        max_concurrency: int,
        wait_timeout: float,
        lease_seconds: float,
        poll_interval: float = 0.05,
    ) -> QueueAdmission:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if wait_timeout <= 0 or lease_seconds <= 0 or poll_interval <= 0:
            raise ValueError("queue timing values must be positive")
        member = uuid4().hex
        queue_key, active_key, sequence_key = self._keys(queue)
        started = perf_counter()
        last_depth = 0
        try:
            while True:
                result = await self.client.eval(
                    _QUEUE_ACQUIRE_LUA,
                    3,
                    queue_key,
                    active_key,
                    sequence_key,
                    member,
                    max_concurrency,
                    int(lease_seconds * 1000),
                )
                admitted = bool(int(result[0]))
                last_depth = int(result[1])
                active = int(result[2])
                QUEUE_DEPTH.labels(queue=queue).set(last_depth)
                QUEUE_ACTIVE.labels(queue=queue).set(active)
                if admitted:
                    elapsed = perf_counter() - started
                    QUEUE_WAIT.labels(queue=queue, outcome="admitted").observe(elapsed)
                    RATE_LIMIT_DECISIONS.labels(
                        layer=f"queue:{queue}", outcome="admitted"
                    ).inc()
                    return QueueAdmission(
                        member=member,
                        wait_ms=round(elapsed * 1000),
                        queue_depth=last_depth,
                        active_leases=active,
                    )
                if perf_counter() - started >= wait_timeout:
                    raise DistributedQueueTimeout(
                        f"distributed queue {queue!r} timed out after {wait_timeout:g}s"
                    )
                await asyncio.sleep(poll_interval)
        except DistributedQueueTimeout:
            await self.release(queue, member)
            elapsed = perf_counter() - started
            QUEUE_WAIT.labels(queue=queue, outcome="timeout").observe(elapsed)
            RATE_LIMIT_DECISIONS.labels(layer=f"queue:{queue}", outcome="timeout").inc()
            QUEUE_DEPTH.labels(queue=queue).set(max(0, last_depth - 1))
            raise
        except BaseException:
            try:
                await self.release(queue, member)
            finally:
                elapsed = perf_counter() - started
                QUEUE_WAIT.labels(queue=queue, outcome="cancelled").observe(elapsed)
                RATE_LIMIT_DECISIONS.labels(
                    layer=f"queue:{queue}", outcome="cancelled"
                ).inc()
            raise

    async def release(self, queue: str, member: str) -> None:
        queue_key, active_key, _ = self._keys(queue)
        await self.client.eval(
            _QUEUE_RELEASE_LUA,
            2,
            queue_key,
            active_key,
            member,
        )
        active = await self.client.zcard(active_key)
        depth = await self.client.zcard(queue_key)
        QUEUE_ACTIVE.labels(queue=queue).set(active)
        QUEUE_DEPTH.labels(queue=queue).set(depth)

    @asynccontextmanager
    async def slot(
        self,
        queue: str,
        *,
        max_concurrency: int,
        wait_timeout: float,
        lease_seconds: float,
    ) -> AsyncIterator[QueueAdmission]:
        admission = await self.acquire(
            queue,
            max_concurrency=max_concurrency,
            wait_timeout=wait_timeout,
            lease_seconds=lease_seconds,
        )
        try:
            yield admission
        finally:
            await self.release(queue, admission.member)

    async def close(self) -> None:
        await self.client.aclose()


__all__ = [
    "DistributedQueueTimeout",
    "QueueAdmission",
    "RedisFairQueueLimiter",
    "RedisTokenBucket",
    "TokenBucketDecision",
]
