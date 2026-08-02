from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest

from safemeal.infrastructure.operations.rate_limit import RedisTokenBucket


def test_live_redis_token_bucket() -> None:
    if os.getenv("RUN_REDIS_INTEGRATION") != "1":
        pytest.skip("set RUN_REDIS_INTEGRATION=1 to run the live Redis test")
    redis_url = os.getenv("REDIS_RATE_LIMIT_URL")
    if not redis_url:
        pytest.skip("set REDIS_RATE_LIMIT_URL to run the live Redis test")

    async def scenario() -> tuple[bool, bool]:
        bucket = RedisTokenBucket(redis_url, prefix=f"safemeal:test:{uuid4().hex}")
        try:
            first = await bucket.acquire("client", capacity=1, refill_per_second=0.01)
            second = await bucket.acquire("client", capacity=1, refill_per_second=0.01)
            return first.allowed, second.allowed
        finally:
            await bucket.close()

    assert asyncio.run(scenario()) == (True, False)
