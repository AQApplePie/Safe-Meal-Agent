"""Document reranking boundary."""

from __future__ import annotations

from typing import Protocol

from safemeal.shared.types import JsonObject


class DocumentReranker(Protocol):
    """Rank retrieved documents by relevance to the current query."""

    enabled: bool

    async def rerank(
        self,
        query: str,
        documents: list[JsonObject],
        top_k: int,
    ) -> list[JsonObject]: ...


__all__ = ["DocumentReranker"]
