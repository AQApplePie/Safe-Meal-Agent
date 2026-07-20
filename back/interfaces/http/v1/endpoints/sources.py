"""Operator endpoints for incremental knowledge source synchronization."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from SafeMealAgent.back.application.use_cases.knowledge.chunking import ChunkStrategyName
from SafeMealAgent.back.infrastructure.ingestion.sync import SourceSyncService
from SafeMealAgent.back.interfaces.http.dependencies import get_source_sync_service

router = APIRouter(prefix="/sources", tags=["Knowledge Sources"])


class SourceSyncRequest(BaseModel):
    source_uri: str = Field(min_length=4, max_length=4096)
    force: bool = False
    chunk_strategy: ChunkStrategyName = "auto"
    delete_missing: bool | None = None


@router.post("/sync")
async def sync_source(
    request: SourceSyncRequest,
    service: SourceSyncService = Depends(get_source_sync_service),
) -> dict:
    state = await service.sync(
        request.source_uri,
        force=request.force,
        chunk_strategy=request.chunk_strategy,
        delete_missing=request.delete_missing,
    )
    return state.__dict__
