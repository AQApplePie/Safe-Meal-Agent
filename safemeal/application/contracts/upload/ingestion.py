"""Durable document-ingestion job contracts and Redis queue adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

ChunkStrategyName = Literal["auto", "recursive", "semantic"]


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
