"""Neo4j readonly Cypher Agent tool."""

import asyncio

from SafeMealAgent.back.infrastructure.retrieval.neo4j import READ_ACCESS
from pydantic import BaseModel, Field

from SafeMealAgent.back.config.settings import settings
from SafeMealAgent.back.infrastructure.tools.registry.runtime import ToolHandler
from SafeMealAgent.back.infrastructure.tools.safety import ensure_readonly_cypher
from SafeMealAgent.back.shared.types import JsonObject, to_json_object

from SafeMealAgent.back.infrastructure.retrieval.neo4j.client import create_driver


class Neo4jQueryArgs(BaseModel):
    cypher: str = Field(description="单条只读 Cypher")
    parameters: JsonObject = Field(default_factory=dict)
    max_rows: int = Field(default=100, ge=1, le=500)


class Neo4jQueryPayload(BaseModel):
    """Neo4j 只读 Cypher 查询返回值。"""

    cypher: str
    parameters: JsonObject = Field(default_factory=dict)
    rows: list[JsonObject] = Field(default_factory=list)
    row_count: int


class Neo4jReadonlyTool(ToolHandler[Neo4jQueryArgs]):
    name = "neo4j_readonly_query"
    description = (
        "在 Neo4j 上执行只读 Cypher，适合实体、关系和路径查询。"
        "禁止 CREATE、MERGE、SET、DELETE 等写操作；不确定图结构时先调用 neo4j_schema。"
    )
    args_schema = Neo4jQueryArgs

    async def run(self, arguments: Neo4jQueryArgs) -> Neo4jQueryPayload:
        cypher = ensure_readonly_cypher(arguments.cypher)
        return await asyncio.to_thread(
            self._query,
            cypher,
            arguments.parameters,
            arguments.max_rows,
        )

    @staticmethod
    def _query(
        cypher: str,
        parameters: JsonObject,
        max_rows: int,
    ) -> Neo4jQueryPayload:
        driver = create_driver()
        try:
            with driver.session(
                database=settings.NEO4J_DATABASE,
                default_access_mode=READ_ACCESS,
            ) as session:
                rows: list[JsonObject] = []
                for row in session.run(cypher, parameters):
                    rows.append(to_json_object(row.data()))
                    if len(rows) >= max_rows:
                        break
                return Neo4jQueryPayload(
                    cypher=cypher,
                    parameters=parameters,
                    rows=rows,
                    row_count=len(rows),
                )
        finally:
            driver.close()
