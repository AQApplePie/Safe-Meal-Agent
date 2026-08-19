"""Durable document-ingestion job contracts and Redis queue adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from safemeal.application.use_cases.knowledge.chunking import ChunkStrategyName


class IngestionJob(BaseModel):
    job_id: str = Field(default_factory=lambda: uuid4().hex)
    tenant_id: str
    filename: str
    content_hex: str
    chunk_strategy: ChunkStrategyName = "auto"
    status: Literal["queued", "running", "succeeded", "failed"] = "queued"
    error: str | None = None
    result: dict[str, object] | None = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        filename: str,
        content: bytes,
        chunk_strategy: ChunkStrategyName,
    ) -> "IngestionJob":
        return cls(
            tenant_id=tenant_id,
            filename=filename,
            content_hex=content.hex(),
            chunk_strategy=chunk_strategy,
        )

    @property
    def content(self) -> bytes:
        return bytes.fromhex(self.content_hex)


class IngestionQueue(Protocol):
    async def enqueue(self, job: IngestionJob) -> None: ...
    async def dequeue(self, timeout_seconds: int = 5) -> IngestionJob | None: ...
    async def update(self, job: IngestionJob) -> None: ...
    async def get(self, job_id: str) -> IngestionJob | None: ...


class RedisIngestionQueue:
    def __init__(self, redis_url: str, *, queue_name: str, ttl_seconds: int) -> None:
        from redis.asyncio import Redis

        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._queue_name = queue_name
        self._ttl = ttl_seconds

    def _key(self, job_id: str) -> str:
        return f"{self._queue_name}:job:{job_id}"

    async def enqueue(self, job: IngestionJob) -> None:
        payload = job.model_dump_json()
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.setex(self._key(job.job_id), self._ttl, payload)
            pipe.lpush(self._queue_name, job.job_id)
            await pipe.execute()

    async def dequeue(self, timeout_seconds: int = 5) -> IngestionJob | None:
        result = await self._redis.brpop(self._queue_name, timeout=timeout_seconds)
        if not result:
            return None
        return await self.get(result[1])

    async def update(self, job: IngestionJob) -> None:
        await self._redis.setex(self._key(job.job_id), self._ttl, job.model_dump_json())

    async def get(self, job_id: str) -> IngestionJob | None:
        raw = await self._redis.get(self._key(job_id))
        return IngestionJob.model_validate_json(raw) if raw else None

    async def close(self) -> None:
        await self._redis.aclose()


__all__ = ["IngestionJob", "IngestionQueue", "RedisIngestionQueue"]
