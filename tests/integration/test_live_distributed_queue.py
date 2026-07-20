from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest

from SafeMealAgent.back.infrastructure.operations.rate_limit import (
    DistributedQueueTimeout,
    RedisFairQueueLimiter,
    RedisTokenBucket,
)


def test_live_redis_queue_is_fifo_across_clients_and_times_out_cleanly() -> None:
    if os.getenv("RUN_REDIS_INTEGRATION") != "1":
        pytest.skip("set RUN_REDIS_INTEGRATION=1 to run the live Redis queue test")

    async def scenario() -> tuple[list[str], bool, int, int]:
        prefix = f"safemeal:test-queue:{uuid4().hex}"
        first = RedisFairQueueLimiter("redis://127.0.0.1:6379/0", prefix=prefix)
        second = RedisFairQueueLimiter("redis://127.0.0.1:6379/0", prefix=prefix)
        order: list[str] = []
        first_entered = asyncio.Event()

        async def holder() -> None:
            async with first.slot(
                "agent", max_concurrency=1, wait_timeout=1, lease_seconds=3
            ):
                order.append("first")
                first_entered.set()
                await asyncio.sleep(0.2)

        async def waiter() -> None:
            await first_entered.wait()
            async with second.slot(
                "agent", max_concurrency=1, wait_timeout=1, lease_seconds=3
            ):
                order.append("second")

        await asyncio.gather(holder(), waiter())

        timed_out = False
        async with first.slot(
            "agent", max_concurrency=1, wait_timeout=1, lease_seconds=3
        ):
            try:
                await second.acquire(
                    "agent",
                    max_concurrency=1,
                    wait_timeout=0.1,
                    lease_seconds=3,
                )
            except DistributedQueueTimeout:
                timed_out = True
        waiting_key, active_key, _ = first._keys("agent")
        waiting = await first.client.zcard(waiting_key)
        active = await first.client.zcard(active_key)
        await first.close()
        await second.close()
        return order, timed_out, waiting, active

    order, timed_out, waiting, active = asyncio.run(scenario())
    assert order == ["first", "second"]
    assert timed_out
    assert waiting == 0
    assert active == 0


def test_live_redis_token_bucket_is_shared_across_clients() -> None:
    if os.getenv("RUN_REDIS_INTEGRATION") != "1":
        pytest.skip("set RUN_REDIS_INTEGRATION=1 to run the live Redis limiter test")

    async def scenario() -> tuple[bool, bool]:
        prefix = f"safemeal:test-rate:{uuid4().hex}"
        first = RedisTokenBucket("redis://127.0.0.1:6379/0", prefix=prefix)
        second = RedisTokenBucket("redis://127.0.0.1:6379/0", prefix=prefix)
        allowed = await first.acquire("shared", capacity=1, refill_per_second=0.01)
        rejected = await second.acquire("shared", capacity=1, refill_per_second=0.01)
        await first.close()
        await second.close()
        return allowed.allowed, rejected.allowed

    first_allowed, second_allowed = asyncio.run(scenario())
    assert first_allowed
    assert not second_allowed
