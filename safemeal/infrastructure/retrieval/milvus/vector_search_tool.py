"""Milvus Agent tools adapter."""

from collections.abc import Awaitable, Callable
from typing import Optional

from pydantic import BaseModel, Field

from safemeal.application.use_cases.knowledge.document_knowledge_service import (
    DocumentKnowledgeService,
)
from safemeal.infrastructure.tools.tool_executor import ToolHandler
from safemeal.shared.types import JsonObject, to_json_object_list


class VectorSearchResult(BaseModel):
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
        document_knowledge_provider: Callable[[], Awaitable[DocumentKnowledgeService]],
    ) -> None:
        """Create the tools with an async, lifecycle-aware service provider."""

        self._document_knowledge_provider = document_knowledge_provider

    async def run(self, arguments: VectorSearchArgs) -> VectorSearchResult:
        document_knowledge = await self._document_knowledge_provider()
        rows = await document_knowledge.search(
            arguments.query,
            top_k=arguments.top_k,
            filter_expr=arguments.filter_expr,
        )
        return VectorSearchResult(
            query=arguments.query,
            documents=to_json_object_list(rows),
            count=len(rows),
        )
