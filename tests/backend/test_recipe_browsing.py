"""Feature 1: public HTTP, real SQL queries, Redis and index migration."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from redis import Redis
from redis.exceptions import ConnectionError
from sqlalchemy import create_engine, event, inspect

from safemeal.infrastructure.cache.recipe_repository import CachedRecipeRepository
from safemeal.infrastructure.persistence.recipe_repository import (
    SqlAlchemyRecipeRepository,
    metadata,
    recipes,
    ingredients,
    recipe_ingredients,
    recipe_steps,
    cuisines,
)
from safemeal.modules.recipe.application.recipe_service import RecipeService
from safemeal.modules.recipe.contracts.catalog import RecipeQuery, RecipeSortField
from safemeal.shared.exceptions import ApplicationError, ResourceNotFoundError


@pytest.fixture
def catalog(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'catalog.sqlite'}")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(cuisines.insert(), [{"id": 1, "name": "家常"}])
        connection.execute(
            ingredients.insert(),
            [
                {"id": 1, "name": "土豆"},
                {"id": 2, "name": "鱼"},
                {"id": 3, "name": "花生"},
            ],
        )
        for index, name, term in [
            (1, "蒸土豆", 1),
            (2, "清蒸鱼", 2),
            (3, "花生拌菜", 3),
            (4, "煮土豆", 1),
        ]:
            connection.execute(
                recipes.insert().values(
                    id=index,
                    name=name,
                    description="完整食谱",
                    servings=2,
                    total_time=20 if index < 3 else 30,
                    difficulty="easy",
                    cuisine_id=1,
                    total_calories=Decimal("100") * index,
                )
            )
            connection.execute(
                recipe_ingredients.insert().values(
                    id=index,
                    recipe_id=index,
                    ingredient_id=term,
                    quantity="100",
                    unit="g",
                    is_main=True,
                    ingredient_type="main",
                )
            )
            connection.execute(
                recipe_steps.insert().values(
                    id=index,
                    recipe_id=index,
                    step_number=1,
                    action="烹饪",
                    instruction="制作完成",
                )
            )
    yield engine, SqlAlchemyRecipeRepository(engine)
    engine.dispose()


@pytest.fixture(scope="module")
def redis_server():
    binary = shutil.which("redis-server")
    if binary is None:
        pytest.skip("redis-server is unavailable; real cache integration not executed")
    with tempfile.TemporaryDirectory(prefix="sm-redis-", dir="/tmp") as directory:
        socket = str(Path(directory) / "redis.sock")
        process = subprocess.Popen(
            [
                binary,
                "--port",
                "0",
                "--unixsocket",
                socket,
                "--unixsocketperm",
                "700",
                "--save",
                "",
                "--appendonly",
                "no",
                "--dir",
                directory,
                "--loglevel",
                "warning",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        redis = Redis(unix_socket_path=socket, decode_responses=True)
        try:
            for _ in range(150):
                try:
                    if redis.ping():
                        break
                except ConnectionError:
                    if process.poll() is not None:
                        pytest.fail(
                            f"redis-server exited: {process.stdout.read().decode()}"
                        )
                    time.sleep(0.02)
            else:
                pytest.fail("disposable Redis did not start")
            yield redis
        finally:
            redis.close()
            process.terminate()
            process.wait(timeout=5)


@pytest.fixture
def live_redis(redis_server):
    redis_server.flushdb()
    return redis_server


class CountedRepository:
    def __init__(self, repository):
        self.repository = repository
        self.reads = 0

    def search(self, query):
        self.reads += 1
        return self.repository.search(query)

    def get(self, recipe_id):
        self.reads += 1
        time.sleep(0.01)
        return self.repository.get(recipe_id)


@pytest.fixture
def cached(catalog, live_redis):
    live_redis.flushdb()  # Only the fixture-owned disposable Redis; never a configured server.
    counted = CountedRepository(catalog[1])
    return counted, CachedRecipeRepository(counted, live_redis)


def test_sql_filter_pagination_order_and_literal_wildcards(catalog):
    repository = catalog[1]
    query = RecipeQuery(
        include_ingredients=("土豆",),
        cuisine="家常",
        sort_by=RecipeSortField.TOTAL_TIME,
        limit=1,
    )
    first = repository.search(query)
    second = repository.search(query.model_copy(update={"offset": 1}))
    assert first.total == second.total == 2
    assert [item.id for item in first.items + second.items] == [1, 4]
    assert repository.search(RecipeQuery(name_contains="%", limit=50)).total == 0
    assert repository.search(RecipeQuery(include_ingredients=("%",))).total == 0
    assert repository.search(RecipeQuery(exclude_ingredients=("花生",))).total == 3
    assert repository.search(RecipeQuery(max_calories=Decimal("200"))).total == 2
    assert repository.search(RecipeQuery(offset=100)).items == ()


def test_sql_page_uses_bounded_queries_without_n_plus_one(catalog):
    statements = []

    def capture(*args):
        statements.append(args[2])

    event.listen(catalog[0], "before_cursor_execute", capture)
    try:
        assert len(catalog[1].search(RecipeQuery(limit=50)).items) == 4
    finally:
        event.remove(catalog[0], "before_cursor_execute", capture)
    assert len(statements) == 4  # count, page, batched ingredients, batched steps


def test_redis_shared_cache_roundtrip_and_query_isolation(cached, live_redis):
    counted, cache = cached
    query = RecipeQuery(limit=1)
    result = cache.search(query)
    second_worker = CachedRecipeRepository(counted, live_redis)
    assert second_worker.search(query) == result
    assert counted.reads == 1
    assert (
        second_worker.search(query.model_copy(update={"offset": 1})).items
        != result.items
    )
    assert counted.reads == 2
    first = cache.get(1)
    assert second_worker.get(1) == first
    assert first.ingredients[0].normalized.unit == "g"


def test_hot_key_concurrent_requests_load_once(cached):
    counted, cache = cached
    with ThreadPoolExecutor(max_workers=16) as workers:
        values = list(workers.map(cache.get, [1] * 32))
    assert all(value.id == 1 for value in values)
    assert counted.reads == 1


def test_negative_cache_and_ttl(cached, live_redis):
    counted, cache = cached
    assert cache.get(9999) is None
    assert CachedRecipeRepository(counted, live_redis).get(9999) is None
    assert counted.reads == 1
    ttl = live_redis.ttl("safemeal:recipes:v1:detail:9999")
    assert 0 < ttl <= 12


def test_corrupt_cache_recovers_without_masking_database_failure(cached, live_redis):
    counted, cache = cached
    live_redis.set("safemeal:recipes:v1:detail:1", "malformed")
    assert cache.get(1).id == 1
    assert counted.reads == 1

    class FailingRepository:
        def get(self, recipe_id):
            raise RuntimeError("database failed")

    failing = CachedRecipeRepository(FailingRepository(), live_redis)
    with pytest.raises(RuntimeError, match="database failed"):
        failing.get(12345)
    assert live_redis.get("safemeal:recipes:v1:detail:12345") is None


def test_redis_outage_falls_back_to_database(catalog):
    redis = Redis(unix_socket_path="/tmp/sm-does-not-exist.sock", decode_responses=True)
    try:
        cache = CachedRecipeRepository(catalog[1], redis)
        assert cache.get(1).id == 1
        assert cache.search(RecipeQuery()).total == 4
    finally:
        redis.close()


def test_local_hot_cache_is_bounded_and_expires(catalog, live_redis):
    counted = CountedRepository(catalog[1])
    cache = CachedRecipeRepository(
        counted, live_redis, local_capacity=2, local_ttl_seconds=0.02
    )
    for index in (1, 2, 3):
        cache.get(index)
    assert len(cache._local) == 2
    live_redis.delete("safemeal:recipes:v1:detail:3")
    time.sleep(0.03)
    cache.get(3)
    assert counted.reads == 4


@pytest.fixture
def api(catalog, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    from safemeal.interfaces.http.dependencies import get_recipe_browse_service
    from safemeal.interfaces.http.routers.recipes import router
    from fastapi.responses import JSONResponse

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/recipes")
    app.dependency_overrides[get_recipe_browse_service] = lambda: RecipeService(
        catalog[1]
    )

    @app.exception_handler(ApplicationError)
    async def error_handler(request, exc):
        return JSONResponse(
            status_code=404 if isinstance(exc, ResourceNotFoundError) else 503,
            content={"error": exc.code},
        )

    with TestClient(app) as client:
        yield client


def test_public_http_list_and_detail(api):
    page = api.get(
        "/api/v1/recipes",
        params={"include_ingredients": "土豆", "limit": 1, "sort_by": "total_time"},
    )
    assert page.status_code == 200
    assert page.json()["total"] == 2
    assert page.json()["has_more"] is True
    assert len(page.json()["items"]) == 1
    assert "steps" not in page.json()["items"][0]
    detail = api.get("/api/v1/recipes/1")
    assert detail.status_code == 200
    assert detail.json()["ingredients"][0]["ingredient"]["name"] == "土豆"
    assert detail.json()["steps"][0]["number"] == 1
    assert api.get("/api/v1/recipes/9999").status_code == 404


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=51",
        "offset=-1",
        "sort_by=sql",
        "sort_order=drop",
        "max_calories=-1",
        "difficulties=unknown",
        "include_ingredients=" + "x" * 101,
    ],
)
def test_http_rejects_invalid_query(api, query):
    assert api.get("/api/v1/recipes?" + query).status_code == 422


@pytest.mark.parametrize("recipe_id", ["0", "-1", "invalid"])
def test_http_rejects_invalid_ids(api, recipe_id):
    assert api.get(f"/api/v1/recipes/{recipe_id}").status_code == 422


def test_new_index_migration_upgrade_downgrade_and_query_plan(catalog):
    path = Path(
        "safemeal/infrastructure/persistence/migrations/versions/20261008_0007_recipe_browse_indexes.py"
    )
    spec = importlib.util.spec_from_file_location("recipe_indexes", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with catalog[0].begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        names = {index["name"] for index in inspect(connection).get_indexes("recipes")}
        assert {name for _, name, _ in migration.INDEXES} <= names
        plan = connection.exec_driver_sql(
            "EXPLAIN QUERY PLAN SELECT id FROM recipes ORDER BY total_time, id LIMIT 10"
        ).all()
        assert "ix_recipe_browse_time_id" in str(plan)
        migration.downgrade()
        assert inspect(connection).get_indexes("recipes") == []
        assert (
            connection.exec_driver_sql("SELECT COUNT(*) FROM recipes").scalar_one() == 4
        )


def test_real_application_browses_without_model_and_maps_missing_recipe(
    catalog, monkeypatch, tmp_path
):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    from safemeal.config.settings import settings

    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(settings, "AGENT_CHECKPOINT_DATABASE_URL", None)
    monkeypatch.setattr(
        settings, "AGENT_CHECKPOINT_PATH", str(tmp_path / "checkpoints.sqlite")
    )
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "ENABLE_LLM", True)
    from safemeal.main import create_application

    app = create_application()
    container = app.state.container
    container._recipe_repository = catalog[1]

    def forbidden():
        pytest.fail("public browsing must not initialize the model gateway")

    monkeypatch.setattr(container, "get_language_model_gateway", forbidden)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/recipes").json()["total"] == 4
        assert client.get("/api/v1/recipes/1").status_code == 200
        missing = client.get("/api/v1/recipes/9999")
        assert missing.status_code == 404
        assert missing.json()["error"] == "resource_not_found"
    assert container._language_model_gateway is None


def test_cache_rejects_search_null_and_supports_binary_redis_payload(
    catalog, live_redis
):
    counted = CountedRepository(catalog[1])
    cache = CachedRecipeRepository(counted, live_redis)
    query = RecipeQuery()
    from hashlib import sha256

    key = f"safemeal:recipes:v1:list:{sha256(query.model_dump_json().encode()).hexdigest()}"
    live_redis.set(key, "null")
    assert cache.search(query).total == 4
    assert counted.reads == 1
    # Separate client with binary responses on the same fixture-owned socket.
    binary = Redis(
        unix_socket_path=live_redis.connection_pool.connection_kwargs["path"]
    )
    try:
        cold = CachedRecipeRepository(counted, binary)
        cold.get(9999)
        assert CachedRecipeRepository(counted, binary).get(9999) is None
    finally:
        binary.close()


def test_index_migration_preflights_conflicts_before_creating_anything(catalog):
    path = Path(
        "safemeal/infrastructure/persistence/migrations/versions/20261008_0007_recipe_browse_indexes.py"
    )
    spec = importlib.util.spec_from_file_location("recipe_indexes_conflicts", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with catalog[0].begin() as connection:
        connection.exec_driver_sql(
            "CREATE INDEX ix_recipe_browse_calories_id ON recipes(total_calories, id)"
        )
        migration.op = Operations(MigrationContext.configure(connection))
        with pytest.raises(RuntimeError, match="Unexpected existing indexes"):
            migration.upgrade()
        assert {row["name"] for row in inspect(connection).get_indexes("recipes")} == {
            "ix_recipe_browse_calories_id"
        }


def test_hot_key_reads_do_not_extend_local_freshness(catalog, live_redis, monkeypatch):
    import safemeal.infrastructure.cache.recipe_repository as cache_module

    clock = [0.0]
    monkeypatch.setattr(cache_module, "monotonic", lambda: clock[0])
    counted = CountedRepository(catalog[1])
    cache = CachedRecipeRepository(counted, live_redis)
    cache.get(1)
    clock[0] = 0.8
    cache.get(1)
    assert counted.reads == 1
    live_redis.delete("safemeal:recipes:v1:detail:1")
    clock[0] = 1.1
    cache.get(1)
    assert counted.reads == 2


def test_oversized_values_do_not_enter_redis_or_local_cache(catalog, live_redis):
    recipe = catalog[1].get(1).model_copy(update={"description": "x" * (300 * 1024)})

    class LargeRepository:
        def get(self, recipe_id):
            return recipe

    cache = CachedRecipeRepository(LargeRepository(), live_redis)
    assert cache.get(1) == recipe
    assert live_redis.get("safemeal:recipes:v1:detail:1") is None
    assert not cache._local


def test_sql_equal_sort_values_keep_stable_id_order(catalog):
    query = RecipeQuery(sort_by=RecipeSortField.TOTAL_TIME, limit=1)
    first = catalog[1].search(query)
    second = catalog[1].search(query.model_copy(update={"offset": 1}))
    assert first.items[0].id == 1
    assert second.items[0].id == 2
    assert first.items[0].total_time_minutes == second.items[0].total_time_minutes


def test_count_keeps_null_cuisine_and_filtered_totals(catalog):
    engine, repository = catalog
    with engine.begin() as conn:
        conn.execute(recipes.update().where(recipes.c.id == 1).values(cuisine_id=None))
    unfiltered = repository.search(RecipeQuery(limit=1))
    filtered = repository.search(RecipeQuery(cuisine="家常", limit=1))
    assert unfiltered.total == 4 and filtered.total == 3
    assert repository.get(1).cuisine is None
    assert repository.search(RecipeQuery(include_ingredients=("土豆",))).total == 2
    assert (
        repository.search(
            RecipeQuery(cuisine="家常", include_ingredients=("土豆",))
        ).total
        == 1
    )
    assert repository.search(RecipeQuery(cuisine="不存在")).total == 0


def test_difficulty_time_index_migration_preserves_catalog(catalog):
    path = (
        Path(__file__).resolve().parents[2]
        / "safemeal/infrastructure/persistence/migrations/versions/20261009_0014_recipe_difficulty_time_index.py"
    )
    spec = importlib.util.spec_from_file_location("difficulty_time_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine, repository = catalog
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
            indexes = {
                item["name"]: item for item in inspect(conn).get_indexes("recipes")
            }
            assert indexes[module.NAME]["column_names"] == [
                "difficulty",
                "total_time",
                "id",
            ]
            module.downgrade()
            assert module.NAME not in {
                item["name"] for item in inspect(conn).get_indexes("recipes")
            }
    assert repository.search(RecipeQuery()).total == 4
