"""LightRAG 应用用例服务。"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator

from SafeMealAgent.back.application.contracts.lightrag import LightRAGInsertResult, SearchMode
from SafeMealAgent.back.application.errors import ExternalProviderError
from SafeMealAgent.back.application.ports import LightRAGGateway
from SafeMealAgent.back.config.settings import settings
from SafeMealAgent.back.shared.types import JsonObject


class LightRAGQueryResult:
    """Non-streaming LightRAG query result."""

    def __init__(
        self,
        *,
        query: str,
        response: str,
        mode: SearchMode,
        metadata: JsonObject,
    ) -> None:
        self.query = query
        self.response = response
        self.mode = mode
        self.metadata = metadata


class LightRAGApplicationService:
    """Coordinate LightRAG use cases without exposing infrastructure to HTTP."""

    def __init__(self, gateway: LightRAGGateway) -> None:
        self._gateway = gateway

    async def query(
        self,
        *,
        query: str,
        mode: SearchMode,
        top_k: int | None,
    ) -> LightRAGQueryResult:
        try:
            answer = await asyncio.wait_for(
                self._gateway.query(
                    query=query,
                    mode=mode,
                    top_k=top_k,
                    stream=False,
                ),
                timeout=settings.LIGHTRAG_OPERATION_TIMEOUT,
            )
        except Exception as exc:
            raise ExternalProviderError("LightRAG query failed") from exc
        return LightRAGQueryResult(
            query=query,
            response=str(answer),
            mode=mode,
            metadata={
                "top_k": top_k or self._gateway.default_top_k,
                "working_dir": self._gateway.working_dir,
            },
        )

    async def query_stream(
        self,
        *,
        query: str,
        mode: SearchMode,
        top_k: int | None,
    ) -> AsyncGenerator[str, None]:
        try:
            response = await asyncio.wait_for(
                self._gateway.query(
                    query=query,
                    mode=mode,
                    top_k=top_k,
                    stream=True,
                ),
                timeout=settings.LIGHTRAG_OPERATION_TIMEOUT,
            )
        except Exception as exc:
            raise ExternalProviderError("LightRAG stream query failed") from exc
        if isinstance(response, str):
            if response:
                yield response
            return
        async for chunk in response:
            yield str(chunk)

    async def insert_documents(self, documents: list[str]) -> LightRAGInsertResult:
        try:
            return await asyncio.wait_for(
                self._gateway.insert_documents(documents),
                timeout=settings.LIGHTRAG_OPERATION_TIMEOUT,
            )
        except Exception as exc:
            raise ExternalProviderError("LightRAG document insertion failed") from exc

    def get_index_stats(self) -> JsonObject:
        try:
            return self._gateway.get_index_stats()
        except Exception as exc:
            raise ExternalProviderError("LightRAG index stats failed") from exc
