"""实现文档摄取基础设施适配。"""

from __future__ import annotations

import asyncio
from loguru import logger

from safemeal.infrastructure.ingestion.redis_queue import RedisIngestionQueue
from safemeal.bootstrap.composition.application_container import ApplicationContainer
from safemeal.config.settings import settings


async def run_worker() -> None:
    if not settings.INGESTION_QUEUE_URL:
        raise RuntimeError("INGESTION_QUEUE_URL is required for the worker")
    queue = RedisIngestionQueue(
        settings.INGESTION_QUEUE_URL,
        queue_name=settings.INGESTION_QUEUE_NAME,
        ttl_seconds=settings.INGESTION_JOB_TTL_SECONDS,
    )
    container = ApplicationContainer()
    ingestion = await container.get_uploaded_document_ingestion_service()
    logger.info("ingestion.worker.started queue={}", settings.INGESTION_QUEUE_NAME)
    try:
        while True:
            job = await queue.dequeue()
            if job is None:
                continue
            try:
                job.status = "running"
                await queue.update(job)
                result = await ingestion.ingest(
                    original_filename=job.filename,
                    content=job.content,
                    chunk_strategy=job.chunk_strategy,
                    tenant_id=job.tenant_id,
                )
                job.status = "succeeded"
                job.result = result.model_dump(mode="json")
            except Exception as exc:
                logger.exception("ingestion.worker.failed job_id={}", job.job_id)
                job.status = "failed"
                job.error = str(exc)[:2_000]
            await queue.update(job)
    finally:
        await queue.close()
        await container.shutdown()


if __name__ == "__main__":
    asyncio.run(run_worker())
