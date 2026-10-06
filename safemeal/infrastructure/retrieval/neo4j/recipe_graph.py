"""
Neo4j数据库客户端封装
仅供图谱初始化和图快照基础设施使用；Agent 查询使用只读 Neo4j Tool。
"""

from contextlib import contextmanager
from typing import Optional

from neo4j import GraphDatabase
from neo4j.graph import Graph

from safemeal.config.settings import settings
from safemeal.shared.types import JsonObject, to_json_object


def create_driver():

    auth = None
    if settings.NEO4J_USER and settings.NEO4J_PASSWORD:
        auth = (settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    return GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=auth,
        connection_timeout=settings.NEO4J_CONNECTION_TIMEOUT,
    )


class RecipeGraphDatabase:
    """对 neo4j 驱动程序的轻量级封装。"""

    def __init__(
        self,
        uri: str,
        user: Optional[str],
        password: Optional[str],
        database: Optional[str] = None,
        max_connection_lifetime: int | None = None,
        connection_timeout: float | None = None,
    ) -> None:
        auth: tuple[str, str] | None = None
        if user and password:
            auth = (user, password)

        if max_connection_lifetime is not None and connection_timeout is not None:
            self._driver = GraphDatabase.driver(
                uri,
                auth=auth,
                max_connection_lifetime=max_connection_lifetime,
                connection_timeout=connection_timeout,
            )
        elif max_connection_lifetime is not None:
            self._driver = GraphDatabase.driver(
                uri,
                auth=auth,
                max_connection_lifetime=max_connection_lifetime,
            )
        elif connection_timeout is not None:
            self._driver = GraphDatabase.driver(
                uri,
                auth=auth,
                connection_timeout=connection_timeout,
            )
        else:
            self._driver = GraphDatabase.driver(uri, auth=auth)
        self._database = database

    def close(self) -> None:
        if self._driver:
            self._driver.close()

    @contextmanager
    def _session(self):
        session = self._driver.session(database=self._database)
        try:
            yield session
        finally:
            session.close()

    def execute(self, query: str, parameters: Optional[JsonObject] = None) -> None:
        with self._session() as session:
            session.execute_write(lambda tx: tx.run(query, parameters or {}).consume())

    def fetch(
        self,
        query: str,
        parameters: Optional[JsonObject] = None,
    ) -> list[JsonObject]:

        with self._session() as session:
            return session.execute_read(
                lambda tx: [
                    to_json_object(record.data())
                    for record in tx.run(query, parameters or {})
                ]
            )

    def fetch_graph(
        self,
        query: str,
        parameters: Optional[JsonObject] = None,
    ) -> Graph:
        with self._session() as session:
            return session.execute_read(
                lambda tx: tx.run(query, parameters or {}).graph()
            )
