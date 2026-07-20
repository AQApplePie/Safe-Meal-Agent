"""Neo4j schema inspection Agent tool."""

import asyncio

from SafeMealAgent.back.infrastructure.retrieval.neo4j import READ_ACCESS
from pydantic import BaseModel, Field

from SafeMealAgent.back.config.settings import settings
from SafeMealAgent.back.infrastructure.tools.registry.runtime import ToolHandler
from SafeMealAgent.back.shared.types import JsonObject, to_json_object_list

from SafeMealAgent.back.infrastructure.retrieval.neo4j.client import create_driver


class Neo4jSchemaArgs(BaseModel):
    include_properties: bool = True


class Neo4jSchemaPayload(BaseModel):
    """Neo4j schema 工具返回值。"""

    database: str = "neo4j"
    labels: list[str] = Field(default_factory=list)
    relationship_types: list[str] = Field(default_factory=list)
    properties: list[JsonObject] = Field(default_factory=list)


class Neo4jSchemaTool(ToolHandler[Neo4jSchemaArgs]):
    name = "neo4j_schema"
    description = "读取 Neo4j 节点标签、关系类型和属性。生成 Cypher 前如果不了解结构，应先调用本工具。"
    args_schema = Neo4jSchemaArgs

    async def run(self, arguments: Neo4jSchemaArgs) -> Neo4jSchemaPayload:
        return await asyncio.to_thread(self._schema, arguments.include_properties)

    @staticmethod
    def _schema(include_properties: bool) -> Neo4jSchemaPayload:
        driver = create_driver()
        try:
            with driver.session(
                database=settings.NEO4J_DATABASE,
                default_access_mode=READ_ACCESS,
            ) as session:
                labels = [
                    row["label"]
                    for row in session.run(
                        "MATCH (n) UNWIND labels(n) AS label RETURN DISTINCT label"
                    )
                ]
                relations = [
                    row["relationshipType"]
                    for row in session.run(
                        "MATCH ()-[r]->() "
                        "RETURN DISTINCT type(r) AS relationshipType"
                    )
                ]
                properties: list[JsonObject] = []
                if include_properties:
                    query = (
                        "MATCH (n) UNWIND labels(n) AS label "
                        "UNWIND keys(n) AS property "
                        "RETURN DISTINCT label, property LIMIT 300"
                    )
                    properties = to_json_object_list(
                        [row.data() for row in session.run(query)]
                    )
                return Neo4jSchemaPayload(
                    labels=labels,
                    relationship_types=relations,
                    properties=properties,
                )
        finally:
            driver.close()
