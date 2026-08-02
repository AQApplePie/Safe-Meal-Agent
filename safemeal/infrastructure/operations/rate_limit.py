"""Minimal Redis token bucket used at the HTTP request boundary."""

from __future__ import annotations

from dataclasses import dataclass

import redis.asyncio as redis


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


@dataclass(frozen=True, slots=True)
class TokenBucketDecision:
    allowed: bool
    remaining: float
    retry_after_ms: int


class RedisTokenBucket:
    """One atomic, shared request limiter backed by Redis."""

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
        return TokenBucketDecision(
            allowed=bool(int(result[0])),
            remaining=float(result[1]),
            retry_after_ms=int(result[2]),
        )

    async def close(self) -> None:
        await self.client.aclose()


__all__ = ["RedisTokenBucket", "TokenBucketDecision"]
