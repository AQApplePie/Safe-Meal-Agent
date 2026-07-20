"""LightRAG Agent tool adapter."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from SafeMealAgent.back.infrastructure.tools.registry.runtime import ToolHandler
from SafeMealAgent.back.application.contracts.lightrag import SearchMode

if TYPE_CHECKING:
    from SafeMealAgent.back.infrastructure.retrieval.lightrag.service import LightRAGService


class LightRAGSearchPayload(BaseModel):
    """LightRAG 查询返回值。"""

    query: str
    mode: str
    response: str


class LightRAGSearchArgs(BaseModel):
    query: str
    mode: SearchMode = "hybrid"
    top_k: int = Field(default=5, ge=1, le=20)


class LightRAGSearchTool(ToolHandler[LightRAGSearchArgs]):
    name = "lightrag_search"
    description = (
        "查询已建立的 LightRAG 文档关系索引，适合跨文档、多跳关系和全局主题总结。"
        "它不是 Neo4j 查询失败后的固定兜底，应由 Agent 根据任务需要选择。"
    )
    args_schema = LightRAGSearchArgs

    def __init__(
        self,
        service_provider: Callable[[], "LightRAGService"],
    ) -> None:
        """Create the tool with a service owned by the composition root."""

        self._service_provider = service_provider

    async def run(self, arguments: LightRAGSearchArgs) -> LightRAGSearchPayload:
        service = self._service_provider()
        response = await service.query(
            query=arguments.query,
            mode=arguments.mode,
            top_k=arguments.top_k,
            stream=False,
        )
        return LightRAGSearchPayload(
            query=arguments.query,
            mode=arguments.mode,
            response=str(response),
        )
