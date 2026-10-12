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


# 方法说明：create_driver
# 作用：按连接配置创建 Neo4j 驱动。
# 入参：
#   无显式入参。
# 出参：Neo4j Driver；使用给定连接配置创建的图驱动。
def create_driver():

    auth = None
    if settings.NEO4J_USER and settings.NEO4J_PASSWORD:
        auth = (settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    return GraphDatabase.driver(
        settings.NEO4J_URI,
        auth=auth,
        connection_timeout=settings.NEO4J_CONNECTION_TIMEOUT,
    )


# 类说明（业务或基础设施实现类）：RecipeGraphDatabase
# 作用：对 neo4j 驱动程序的轻量级封装。
class RecipeGraphDatabase:
    """对 neo4j 驱动程序的轻量级封装。"""

    # 方法说明：__init__
    # 作用：初始化Neo4j 食谱图数据库封装，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   uri（str）：当前外部资源或服务的连接地址。
    #   user（Optional[str]）：当前用户的仓储记录。
    #   password（Optional[str]）：用户提供的明文密码，仅用于校验或生成哈希。
    #   database（Optional[str]）：数据库名称或数据库配置；默认值为 None。
    #   max_connection_lifetime（int | None）：外部连接最长存活时长，单位秒；默认值为 None。
    #   connection_timeout（float | None）：建立外部连接的超时时长，单位秒；默认值为 None。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
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
            # 实例属性说明：_driver
            # 作用：外部数据库连接驱动。
            self._driver = GraphDatabase.driver(
                uri,
                auth=auth,
                max_connection_lifetime=max_connection_lifetime,
                connection_timeout=connection_timeout,
            )
        elif max_connection_lifetime is not None:
            # 实例属性说明：_driver
            # 作用：外部数据库连接驱动。
            self._driver = GraphDatabase.driver(
                uri,
                auth=auth,
                max_connection_lifetime=max_connection_lifetime,
            )
        elif connection_timeout is not None:
            # 实例属性说明：_driver
            # 作用：外部数据库连接驱动。
            self._driver = GraphDatabase.driver(
                uri,
                auth=auth,
                connection_timeout=connection_timeout,
            )
        else:
            # 实例属性说明：_driver
            # 作用：外部数据库连接驱动。
            self._driver = GraphDatabase.driver(uri, auth=auth)
        # 实例属性说明：_database
        # 作用：数据库名称或数据库配置。
        self._database = database

    # 方法说明：close
    # 作用：关闭当前组件拥有的客户端或连接，释放外部资源。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def close(self) -> None:
        if self._driver:
            self._driver.close()

    # 方法说明：_session
    # 作用：创建 Neo4j 会话供图查询与写入使用。
    # 入参：
    #   无显式入参。
    # 出参：按实现返回；可执行图查询与写入的 Neo4j 会话。
    @contextmanager
    def _session(self):
        session = self._driver.session(database=self._database)
        try:
            yield session
        finally:
            session.close()

    # 方法说明：execute
    # 作用：根据已校验的调用参数执行Neo4j 食谱图数据库封装。
    # 入参：
    #   query（str）：结构化查询条件或检索问题。
    #   parameters（Optional[JsonObject]）：底层接口使用的参数映射；默认值为 None。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def execute(self, query: str, parameters: Optional[JsonObject] = None) -> None:
        with self._session() as session:
            session.execute_write(lambda tx: tx.run(query, parameters or {}).consume())

    # 方法说明：fetch
    # 作用：通过Neo4j 食谱图数据库封装取得目标数据并转换为内部结构。
    # 入参：
    #   query（str）：结构化查询条件或检索问题。
    #   parameters（Optional[JsonObject]）：底层接口使用的参数映射；默认值为 None。
    # 出参：list[JsonObject]；JSON 字段映射的集合。
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

    # 方法说明：fetch_graph
    # 作用：读取图数据并组织成可供业务使用的结构。
    # 入参：
    #   query（str）：结构化查询条件或检索问题。
    #   parameters（Optional[JsonObject]）：底层接口使用的参数映射；默认值为 None。
    # 出参：Graph；可执行图对象。
    def fetch_graph(
        self,
        query: str,
        parameters: Optional[JsonObject] = None,
    ) -> Graph:
        with self._session() as session:
            return session.execute_read(
                lambda tx: tx.run(query, parameters or {}).graph()
            )
