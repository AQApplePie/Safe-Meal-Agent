"""定义应用层依赖的能力端口。"""

from __future__ import annotations

from typing import Protocol

from safemeal.shared.types import JsonObject


class DocumentReranker(Protocol):

    enabled: bool

    async def rerank(
        self,
        query: str,
        documents: list[JsonObject],
        top_k: int,
    ) -> list[JsonObject]: ...


__all__ = ["DocumentReranker"]
