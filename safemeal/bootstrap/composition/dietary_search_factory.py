"""装配饮食安全图检索能力。"""

from neo4j import GraphDatabase
from safemeal.config.settings import settings
from safemeal.infrastructure.retrieval.neo4j.safe_recipe_search import (
    SafeRecipeGraphSearch,
)


# 方法说明：create_dietary_search
# 作用：按配置装配菜谱仓储、图检索与安全查询依赖。
# 入参：
#   无显式入参。
# 出参：SafeRecipeGraphSearch；Neo4j 安全食谱图查询器。
def create_dietary_search() -> SafeRecipeGraphSearch:
    # 方法说明：driver_factory
    # 作用：根据当前 Neo4j 地址和认证配置创建图数据库驱动。
    # 入参：
    #   无显式入参。
    # 出参：按实现返回；Neo4j Driver；已按连接与认证配置创建的图数据库驱动。
    def driver_factory():
        auth = (
            (settings.NEO4J_USER, settings.NEO4J_PASSWORD)
            if settings.NEO4J_USER and settings.NEO4J_PASSWORD
            else None
        )
        return GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=auth,
            connection_timeout=settings.NEO4J_CONNECTION_TIMEOUT,
        )

    return SafeRecipeGraphSearch(driver_factory, settings.NEO4J_DATABASE)
