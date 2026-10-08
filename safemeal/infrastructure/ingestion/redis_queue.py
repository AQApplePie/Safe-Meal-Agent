from safemeal.modules.knowledge.contracts.ingestion import IngestionJob


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
