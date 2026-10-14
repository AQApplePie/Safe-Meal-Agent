"""SQL truth, real Redis ZSets, fenced snapshot recovery and lifespan worker."""

import asyncio
from datetime import date, datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import time
from zoneinfo import ZoneInfo

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import pytest
from redis import Redis
from sqlalchemy import create_engine, event, inspect, select, text

from test_recipe_browsing import live_redis as live_redis, redis_server as redis_server
from safemeal.infrastructure.cache.ranking_store import RedisRankingStore
from safemeal.infrastructure.cache.ranking_worker import RankingWorker
from safemeal.infrastructure.persistence.history_repository import history
from safemeal.infrastructure.persistence.ranking_repository import (
    SqlAlchemyRankingRepository,
)
from safemeal.infrastructure.persistence.reaction_repository import (
    reactions,
    SqlAlchemyReactionRepository,
)
from safemeal.infrastructure.persistence.recipe_repository import metadata, recipes
from safemeal.modules.interaction.application.ranking_service import RankingService
from safemeal.modules.interaction.contracts.models import InteractionActor
from safemeal.modules.interaction.contracts.ranking import RankedRecipe, RankingSnapshot
from safemeal.shared.exceptions import (
    ApplicationError,
    DatabaseUnavailableError,
    InputValidationError,
)

NOW = datetime(2026, 10, 8, 4, tzinfo=timezone.utc)
DAY = date(2026, 10, 8)


@pytest.fixture(autouse=True)
def configured_http(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rankings.sqlite'}")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    metadata.create_all(engine)
    history.create(engine)
    reactions.create(engine)
    with engine.begin() as connection:
        connection.execute(
            recipes.insert(), [{"id": n, "name": f"食谱{n}"} for n in range(1, 7)]
        )
        for recipe_id, count in [(1, 3), (2, 2), (3, 2), (4, 1)]:
            connection.execute(
                history.insert(),
                [
                    dict(
                        tenant_id="default",
                        subject=f"viewer{n}",
                        recipe_id=recipe_id,
                        last_viewed_at=NOW.replace(tzinfo=None),
                    )
                    for n in range(count)
                ],
            )
        connection.execute(
            history.insert(),
            [
                dict(
                    tenant_id="other",
                    subject="one",
                    recipe_id=5,
                    last_viewed_at=NOW.replace(tzinfo=None),
                ),
                dict(
                    tenant_id="default",
                    subject="past",
                    recipe_id=6,
                    last_viewed_at=datetime(2026, 10, 7, 15, 59, 59),
                ),
            ],
        )
        connection.execute(
            reactions.insert(),
            [
                dict(tenant_id="default", subject="one", recipe_id=1, kind="like"),
                dict(tenant_id="default", subject="one", recipe_id=1, kind="favorite"),
                dict(tenant_id="default", subject="two", recipe_id=2, kind="like"),
                dict(tenant_id="other", subject="one", recipe_id=5, kind="favorite"),
            ],
        )
    yield engine, SqlAlchemyRankingRepository(engine)
    engine.dispose()


def service(database, store=None, cap=1000, clock=None):
    return RankingService(
        database[1],
        store,
        cap=cap,
        day_timezone=ZoneInfo("Asia/Shanghai"),
        clock=clock or (lambda: NOW),
    )


def snapshot(score=1, name="食谱1", items=None, mode="popular"):
    return RankingSnapshot(
        mode=mode,
        day=DAY if mode == "today" else None,
        updated_at=NOW,
        items=items
        if items is not None
        else (RankedRecipe(recipe_id=1, recipe_name=name, score=score),),
        truncated=False,
    )


def test_sql_metrics_tenant_isolation_ties_and_paging(database):
    rankings = service(database)
    today = rankings.read("default", "today", limit=2)
    assert today.source == "database" and today.day == DAY
    assert [(item.recipe_id, item.score, item.rank) for item in today.items] == [
        (1, 3, 1),
        (3, 2, 2),
    ]
    assert today.has_more and today.ranked_count == 4
    second = rankings.read("default", "today", offset=2, limit=2)
    assert [(item.recipe_id, item.rank) for item in second.items] == [(2, 3), (4, 4)]
    assert not second.has_more
    popular = rankings.read("default", "popular")
    assert [(item.recipe_id, item.score) for item in popular.items] == [(1, 2), (2, 1)]
    assert popular.day is None
    assert [item.recipe_id for item in rankings.read("other").items] == [5]
    empty = rankings.read("new-tenant")
    assert empty.items == () and empty.ranked_count == 0


def test_day_timezone_boundaries_and_rollover(database):
    engine, _ = database
    with engine.begin() as connection:
        connection.execute(
            history.insert(),
            [
                dict(
                    tenant_id="boundaries",
                    subject="start",
                    recipe_id=1,
                    last_viewed_at=datetime(2026, 10, 7, 16),
                ),
                dict(
                    tenant_id="boundaries",
                    subject="end",
                    recipe_id=2,
                    last_viewed_at=datetime(2026, 10, 8, 16),
                ),
            ],
        )
    assert [item.recipe_id for item in service(database).read("boundaries").items] == [
        1
    ]
    tomorrow = service(database, clock=lambda: NOW + timedelta(days=1)).read(
        "boundaries"
    )
    assert tomorrow.day == DAY + timedelta(days=1)
    assert [item.recipe_id for item in tomorrow.items] == [2]


def test_cap_and_invalid_pagination(database):
    rankings = service(database, cap=2)
    page = rankings.read("default")
    assert page.truncated and page.ranked_count == 2
    assert len(page.items) == 2
    for mode, offset, limit in [
        ("bad", 0, 1),
        ("today", -1, 1),
        ("today", 2, 1),
        ("today", 0, 51),
    ]:
        with pytest.raises(InputValidationError):
            rankings.read("default", mode, offset, limit)


def test_tenant_discovery_is_batched(database):
    repo = database[1]
    assert repo.tenants(None, 1) == ("default",)
    assert repo.tenants("default", 1) == ("other",)
    assert repo.tenants("other", 1) == ()


def test_sql_query_budget_and_day_index(database):
    engine, _ = database
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def capture(_, __, statement, ___, ____, _____):
        statements.append(statement)

    service(database).read("default")
    assert len(statements) == 1
    with engine.connect() as connection:
        plan = connection.execute(
            text(
                "EXPLAIN QUERY PLAN SELECT recipe_id FROM recipe_view_history WHERE tenant_id='default' AND last_viewed_at >= '2026-10-07 16:00:00.000000' AND last_viewed_at < '2026-10-08 16:00:00.000000'"
            )
        ).all()
    assert any("ix_recipe_history_ranking_day" in str(row) for row in plan)


def test_real_zset_absolute_refresh_and_cancel(database, live_redis):
    store = RedisRankingStore(live_redis)
    rankings = service(database, store)
    assert rankings.read("default").source == "database"
    rankings.refresh_batch(None, 50)
    cached = rankings.read("default")
    assert cached.source == "redis"
    assert [(item.recipe_id, item.score) for item in cached.items] == [
        (1, 3),
        (3, 2),
        (2, 2),
        (4, 1),
    ]
    key = store._keys("default", "today", DAY)[0]
    assert live_redis.type(key) == "zset" and live_redis.zscore(key, "0000000001") == 3
    rankings.refresh_batch(None, 50)
    assert live_redis.zscore(key, "0000000001") == 3
    SqlAlchemyReactionRepository(database[0]).set_state(
        1, InteractionActor(tenant_id="default", subject="one"), "like", False
    )
    assert (
        rankings.read("default", "popular").items[0].score == 2
    )  # async snapshot still old
    rankings.refresh_batch(None, 50)
    refreshed = rankings.read("default", "popular")
    assert [(item.recipe_id, item.score) for item in refreshed.items] == [
        (2, 1),
        (1, 1),
    ]


def test_lost_redis_snapshot_recovers_from_sql(database, live_redis):
    store = RedisRankingStore(live_redis)
    rankings = service(database, store)
    rankings.refresh_batch(None, 50)
    expected = rankings.read("default").items
    live_redis.flushdb()  # Fixture-owned disposable server only.
    fallback = rankings.read("default")
    assert fallback.source == "database" and fallback.items == expected
    rankings.refresh_batch(None, 50)
    assert rankings.read("default").source == "redis"
    assert rankings.read("default").items == expected


@pytest.mark.parametrize(
    "damage", ["scores", "names", "meta", "wrong_type", "bad_score"]
)
def test_partial_loss_and_corruption_fallback(database, live_redis, damage):
    store = RedisRankingStore(live_redis)
    rankings = service(database, store)
    rankings.refresh_batch(None, 50)
    scores, names, meta = store._keys("default", "today", DAY)
    if damage == "scores":
        live_redis.delete(scores)
    elif damage == "names":
        live_redis.delete(names)
    elif damage == "meta":
        live_redis.set(meta, "not-json")
    elif damage == "wrong_type":
        live_redis.delete(scores)
        live_redis.set(scores, "bad")
    else:
        live_redis.zadd(scores, {"0000000001": 1.5})
    assert rankings.read("default").source == "database"
    rankings.refresh_batch(None, 50)
    assert rankings.read("default").source == "redis"


def test_outage_falls_back_and_database_failure_is_not_empty(database):
    offline = Redis(
        unix_socket_path="/tmp/safemeal-ranking-nonexistent.sock",
        socket_connect_timeout=0.02,
        socket_timeout=0.02,
    )
    try:
        rankings = service(database, RedisRankingStore(offline))
        assert rankings.read("default").source == "database"
        assert rankings.refresh_batch(None, 50) is None
        history.drop(database[0])
        with pytest.raises(DatabaseUnavailableError):
            rankings.read("default")
    finally:
        offline.close()


def test_expired_worker_cannot_publish_or_release_new_lease(live_redis):
    store = RedisRankingStore(live_redis)
    old = store.acquire("default")
    assert old and store.acquire("default") is None
    live_redis.delete(store._prefix("default") + ":lease")
    new = store.acquire("default")
    assert new and new != old
    assert store.publish("default", new, snapshot(score=2))
    assert not store.publish("default", old, snapshot(score=9))
    store.release("default", old)
    assert store.acquire("default") is None
    assert store.read("default", "popular", None, 0, 20).items[0].score == 2
    store.release("default", new)
    assert store.acquire("default")
    assert live_redis.keys("*:tmp:*") == []


def test_empty_snapshot_and_ttl(live_redis):
    store = RedisRankingStore(live_redis, ttl_seconds=10)
    token = store.acquire("empty")
    assert store.publish("empty", token, snapshot(items=()))
    result = store.read("empty", "popular", None, 0, 20)
    assert result.source == "redis" and result.items == () and result.ranked_count == 0
    keys = store._keys("empty", "popular", None)
    assert 0 < live_redis.ttl(keys[2]) <= 10
    live_redis.delete(keys[2])
    assert store.read("empty", "popular", None, 0, 20) is None


def test_redis_numeric_tie_order_binary_client_and_tenant_keys(live_redis):
    binary = Redis(
        unix_socket_path=live_redis.connection_pool.connection_kwargs["path"],
        decode_responses=False,
    )
    store = RedisRankingStore(binary)
    token = store.acquire("a:{tenant}")
    items = (
        RankedRecipe(recipe_id=12, recipe_name="十二", score=2),
        RankedRecipe(recipe_id=2, recipe_name="二", score=2),
    )
    assert store.publish("a:{tenant}", token, snapshot(items=items))
    page = store.read("a:{tenant}", "popular", None, 0, 1)
    assert page.items[0].recipe_id == 12 and page.has_more
    assert store.read("a:{tenant}", "popular", None, 1, 1).items[0].rank == 2
    assert store.read("other", "popular", None, 0, 20) is None
    assert "a:{tenant}" not in store._prefix("a:{tenant}")
    binary.close()


def test_date_rollover_does_not_serve_previous_day(database, live_redis):
    store = RedisRankingStore(live_redis)
    rankings = service(database, store)
    rankings.refresh_batch(None, 50)
    next_day = service(database, store, clock=lambda: NOW + timedelta(days=1))
    result = next_day.read("default")
    assert result.source == "database" and result.items == ()
    next_day.refresh_batch(None, 50)
    assert next_day.read("default").source == "redis"


@pytest.mark.asyncio
async def test_worker_retries_and_closes():
    class Flaky:
        calls = 0

        def refresh_batch(self, after, batch_size):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary failure")
            return "next"

    flaky = Flaky()
    worker = RankingWorker(flaky, 0.01, 5)
    worker.start()
    worker.start()
    for _ in range(100):
        if flaky.calls >= 2:
            break
        await asyncio.sleep(0.005)
    await worker.close()
    assert flaky.calls >= 2 and worker._task is None
    calls = flaky.calls
    await asyncio.sleep(0.02)
    assert flaky.calls == calls


def test_http_auth_scope_and_static_route(database):
    from safemeal.interfaces import api_router
    from safemeal.interfaces.http.authentication import get_current_principal, Principal
    from safemeal.interfaces.http.dependencies import (
        get_auth_service,
        get_ranking_service,
    )

    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[get_ranking_service] = lambda: service(database)

    class UnusedAuth:
        def authenticate_access_token(self, token):
            pytest.fail("Missing token must be rejected")

    app.dependency_overrides[get_auth_service] = lambda: UnusedAuth()

    @app.exception_handler(ApplicationError)
    async def errors(_, exc):
        return JSONResponse(status_code=422, content={"code": exc.code})

    with TestClient(app) as client:
        assert client.get("/api/v1/recipes/rankings").status_code == 401
        app.dependency_overrides[get_current_principal] = lambda: Principal(
            subject="one", tenant_id="other"
        )
        page = client.get(
            "/api/v1/recipes/rankings", params={"tenant_id": "default"}
        ).json()
        assert [item["recipe_id"] for item in page["items"]] == [5]
        assert client.get("/api/v1/recipes/rankings?mode=bad").status_code == 422
        assert client.get("/api/v1/recipes/rankings?offset=1000").status_code == 422
        assert client.get("/api/v1/recipes/rankings?limit=51").status_code == 422


def test_migration_adds_only_index_and_preserves_history(tmp_path):
    def load(filename, name):
        spec = importlib.util.spec_from_file_location(
            name,
            Path("safemeal/infrastructure/persistence/migrations/versions") / filename,
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    previous = load("20261008_0009_recipe_view_history.py", "previous_history")
    migration = load("20261008_0010_recipe_ranking_index.py", "ranking_migration")
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    with engine.begin() as connection:
        ops = Operations(MigrationContext.configure(connection))
        previous.op = migration.op = ops
        with pytest.raises(RuntimeError, match="history"):
            migration.upgrade()
        metadata.create_all(connection)
        previous.upgrade()
        connection.execute(recipes.insert().values(id=1, name="one"))
        connection.execute(
            history.insert().values(
                tenant_id="default",
                subject="one",
                recipe_id=1,
                last_viewed_at=NOW.replace(tzinfo=None),
            )
        )
        migration.upgrade()
        assert len(inspect(connection).get_indexes("recipe_view_history")) == 3
        with pytest.raises(RuntimeError, match="Unexpected"):
            migration.upgrade()
        migration.downgrade()
        assert len(inspect(connection).get_indexes("recipe_view_history")) == 2
        assert connection.execute(select(history.c.recipe_id)).scalar_one() == 1
    engine.dispose()


def test_production_lifespan_refreshes_and_stops_without_model(
    database, live_redis, monkeypatch, tmp_path
):
    from safemeal.config.settings import settings
    import safemeal.infrastructure.persistence.ranking_repository as persistence
    from safemeal.interfaces.http.authentication import get_current_principal, Principal

    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(settings, "AGENT_CHECKPOINT_DATABASE_URL", None)
    monkeypatch.setattr(
        settings, "AGENT_CHECKPOINT_PATH", str(tmp_path / "checkpoint.sqlite")
    )
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(
        settings,
        "RECIPE_RANKING_REDIS_URL",
        "unix://" + live_redis.connection_pool.connection_kwargs["path"],
    )
    monkeypatch.setattr(settings, "RECIPE_RANKING_REFRESH_SECONDS", 1)
    monkeypatch.setattr(persistence, "get_engine", lambda: database[0])
    from safemeal.main import create_application

    app = create_application()
    container = app.state.container
    from safemeal.modules.interaction.application.interaction_service import (
        InteractionService,
    )

    container._interaction_service = InteractionService(
        SqlAlchemyReactionRepository(database[0])
    )

    def forbidden():
        pytest.fail("Rankings must not initialize model or recipe cache")

    monkeypatch.setattr(container, "get_language_model_gateway", forbidden)
    monkeypatch.setattr(container, "_get_recipe_repository", forbidden)
    app.dependency_overrides[get_current_principal] = lambda: Principal(subject="one")
    with TestClient(app) as client:
        for _ in range(100):
            response = client.get("/api/v1/recipes/rankings?mode=popular")
            if response.json().get("source") == "redis":
                break
            time.sleep(0.01)
        assert response.status_code == 200 and response.json()["source"] == "redis"
        assert container._ranking_worker._task is not None
        assert client.delete("/api/v1/recipes/1/like").status_code == 200
        for _ in range(200):
            updated = client.get("/api/v1/recipes/rankings?mode=popular").json()
            if updated["source"] == "redis" and updated["items"][0]["recipe_id"] == 2:
                break
            time.sleep(0.01)
        assert [(item["recipe_id"], item["score"]) for item in updated["items"]] == [
            (2, 1),
            (1, 1),
        ]
    assert container._ranking_worker._task is None
    assert container._language_model_gateway is None


def test_profiles_and_script_cache_recovery(live_redis):
    first = RedisRankingStore(live_redis, profile="Asia/Shanghai:1000")
    second = RedisRankingStore(live_redis, profile="UTC:10")
    token = first.acquire("default")
    assert first.publish("default", token, snapshot())
    assert second.read("default", "popular", None, 0, 20) is None
    live_redis.script_flush()
    assert first.read("default", "popular", None, 0, 20).source == "redis"


def test_cache_survives_sql_outage_until_expired(database, live_redis):
    store = RedisRankingStore(live_redis)
    rankings = service(database, store)
    rankings.refresh_batch(None, 50)
    history.drop(database[0])
    assert rankings.read("default").source == "redis"
    live_redis.delete(*store._keys("default", "today", DAY))
    with pytest.raises(DatabaseUnavailableError):
        rankings.read("default")


def test_inactive_tenant_snapshot_expires_to_empty_sql(database, live_redis):
    store = RedisRankingStore(live_redis, ttl_seconds=1)
    rankings = service(database, store)
    rankings.refresh_batch(None, 50)
    with database[0].begin() as connection:
        connection.execute(history.delete().where(history.c.tenant_id == "other"))
        connection.execute(reactions.delete().where(reactions.c.tenant_id == "other"))
    rankings.refresh_batch(None, 50)
    assert rankings.read("other").items  # no remaining facts => not discovered
    for key in store._keys("other", "today", DAY):
        live_redis.pexpire(key, 1)
    time.sleep(0.01)
    result = rankings.read("other")
    assert result.source == "database" and result.items == ()


def test_snapshot_publish_read_is_atomic(live_redis):
    from concurrent.futures import ThreadPoolExecutor

    store = RedisRankingStore(live_redis)
    token = store.acquire("default")
    assert store.publish("default", token, snapshot(score=1, name="old"))

    def publish():
        for _ in range(15):
            assert store.publish("default", token, snapshot(score=2, name="new"))
            assert store.publish("default", token, snapshot(score=1, name="old"))

    def read():
        for _ in range(100):
            page = store.read("default", "popular", None, 0, 20)
            assert page is not None
            assert (page.items[0].score, page.items[0].recipe_name) in {
                (1, "old"),
                (2, "new"),
            }

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(publish), pool.submit(read), pool.submit(read)]
        for future in futures:
            future.result()


@pytest.mark.parametrize("mode", ["today", "popular"])
@pytest.mark.parametrize("tenant", ["default", "other", "missing"])
@pytest.mark.parametrize("limit", [1, 2, 1000])
def test_preaggregated_ranking_matches_previous_query(database, mode, tenant, limit):
    """Optimization preserves tenant, day, kind weighting, ties and top-N semantics."""
    engine, repository = database
    start = datetime(2026, 10, 7, 16, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    facts = history if mode == "today" else reactions
    from sqlalchemy import func

    score = func.count().label("score")
    baseline = (
        select(recipes.c.id, recipes.c.name, score)
        .join(facts, facts.c.recipe_id == recipes.c.id)
        .where(facts.c.tenant_id == tenant)
    )
    if mode == "today":
        baseline = baseline.where(
            facts.c.last_viewed_at >= start.replace(tzinfo=None),
            facts.c.last_viewed_at < end.replace(tzinfo=None),
        )
    baseline = (
        baseline.group_by(recipes.c.id, recipes.c.name)
        .order_by(score.desc(), recipes.c.id.desc())
        .limit(limit)
    )
    with engine.connect() as conn:
        expected = [tuple(row) for row in conn.execute(baseline)]
    actual = repository.aggregate(tenant, mode, start, end, limit)
    assert [(row.recipe_id, row.recipe_name, row.score) for row in actual] == expected
