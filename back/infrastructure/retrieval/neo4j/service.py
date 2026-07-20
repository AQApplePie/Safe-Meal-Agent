# Neo4j infrastructure service for graph import and snapshots.
from pathlib import Path

from loguru import logger

from SafeMealAgent.back.config.settings import settings
from SafeMealAgent.back.shared.types import JsonObject

from SafeMealAgent.back.infrastructure.retrieval.neo4j.client import Neo4jDatabase
from SafeMealAgent.back.infrastructure.retrieval.neo4j.cache import (
    GraphCache,
    convert_graph,
)


class Neo4jGraphService:
    """Neo4j 基础设施服务；自然语言决策由 Agent Tools 负责。"""

    def __init__(self) -> None:
        self._database = Neo4jDatabase(
            settings.NEO4J_URI,
            settings.NEO4J_USER,
            settings.NEO4J_PASSWORD,
            database=settings.NEO4J_DATABASE,
            max_connection_lifetime=settings.NEO4J_MAX_CONNECTION_LIFETIME,
            connection_timeout=settings.NEO4J_CONNECTION_TIMEOUT,
        )
        self._cache = GraphCache(Path(settings.NEO4J_GRAPH_CACHE_PATH))

    def close(self) -> None:
        try:
            self._database.close()
        except Exception as exc:
            logger.warning(f"关闭 Neo4j 驱动失败：{exc}")

    def get_default_graph(self, refresh: bool = False) -> JsonObject:
        if not refresh:
            cached = self._cache.load()
            if cached:
                return cached
        graph = self._database.fetch_graph(settings.NEO4J_DEFAULT_GRAPH_QUERY)
        payload = convert_graph(graph)
        self._cache.save(payload)
        return payload
