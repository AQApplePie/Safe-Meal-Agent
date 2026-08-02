"""Milvus Agent tool adapter."""

from collections.abc import Awaitable, Callable
from typing import Optional

from pydantic import BaseModel, Field

from safemeal.application.use_cases.knowledge.service import KnowledgeService
from safemeal.infrastructure.tools.registry.runtime import ToolHandler
from safemeal.shared.types import JsonObject, to_json_object_list


class VectorSearchPayload(BaseModel):
    """Milvus 语义召回返回值。"""

    query: str
    documents: list[JsonObject] = Field(default_factory=list)
    count: int


class VectorSearchArgs(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)
    filter_expr: Optional[str] = None


class VectorSearchTool(ToolHandler[VectorSearchArgs]):
    name = "milvus_vector_search"
    description = (
        "在 Milvus 中跨文档检索并重排原文证据；结果按文档多样化，适合综合多份资料。"
    )
    args_schema = VectorSearchArgs

    def __init__(
        self,
        service_provider: Callable[[], Awaitable[KnowledgeService]],
    ) -> None:
        """Create the tool with an async, lifecycle-aware service provider."""

        self._service_provider = service_provider

    async def run(self, arguments: VectorSearchArgs) -> VectorSearchPayload:
        service = await self._service_provider()
        rows = await service.search(
            arguments.query,
            top_k=arguments.top_k,
            filter_expr=arguments.filter_expr,
        )
        return VectorSearchPayload(
            query=arguments.query,
            documents=to_json_object_list(rows),
            count=len(rows),
        )
