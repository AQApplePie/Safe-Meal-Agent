"""LightRAG application port."""

from __future__ import annotations

from typing import AsyncGenerator, Protocol

from SafeMealAgent.back.application.contracts.lightrag import LightRAGInsertResult, SearchMode
from SafeMealAgent.back.shared.types import JsonObject


class LightRAGGateway(Protocol):
    """Application-facing LightRAG capability."""

    working_dir: str
    default_top_k: int

    async def query(
        self,
        query: str,
        mode: SearchMode | None = None,
        top_k: int | None = None,
        stream: bool = False,
    ) -> str | AsyncGenerator[str, None]: ...

    async def insert_documents(
        self,
        documents: list[str],
        batch_size: int = 10,
    ) -> LightRAGInsertResult: ...

    def get_index_stats(self) -> JsonObject: ...
