"""Neo4j adapter composition for culinary tools."""

from neo4j import GraphDatabase
from safemeal.config.settings import settings
from safemeal.infrastructure.retrieval.neo4j.safe_recipe_search import (
    SafeRecipeGraphSearch,
)


def create_dietary_search() -> SafeRecipeGraphSearch:
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
