"""Transactional SQL + real Redis delivery, crash recovery and eventual consistency."""

import asyncio
import importlib.util
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from redis.exceptions import ConnectionError
from sqlalchemy import create_engine, func, inspect, select

from test_recipe_browsing import live_redis as live_redis, redis_server as redis_server
from safemeal.infrastructure.cache.ranking_store import RedisRankingStore
from safemeal.infrastructure.messaging.behavior_worker import (
    BehaviorWorker,
    STREAM,
    GROUP,
    DEAD_STREAM,
)
from safemeal.infrastructure.persistence.behavior_outbox import (
    SqlBehaviorOutbox,
    outbox,
    utcnow,
)
from safemeal.infrastructure.persistence.history_repository import (
    SqlAlchemyHistoryRepository,
    history,
)
from safemeal.infrastructure.persistence.reaction_repository import (
    SqlAlchemyReactionRepository,
    reactions,
)
from safemeal.infrastructure.persistence.ranking_repository import (
    SqlAlchemyRankingRepository,
)
from safemeal.infrastructure.persistence.recipe_repository import metadata, recipes
from safemeal.modules.interaction.application.ranking_service import RankingService
from safemeal.modules.interaction.contracts.models import InteractionActor
from safemeal.shared.exceptions import ResourceNotFoundError, DatabaseOperationError

ACTOR = InteractionActor(tenant_id="team", subject="one")


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'events.sqlite'}")
    metadata.create_all(engine)
    reactions.create(engine)
    history.create(engine)
    outbox.create(engine)
    with engine.begin() as connection:
        connection.execute(recipes.insert(), [{"id": 1, "name": "食谱"}])
    yield engine
    engine.dispose()


def row(database):
    with database.connect() as connection:
        return connection.execute(select(outbox)).mappings().first()


def stack(database, live_redis):
    sql = SqlBehaviorOutbox(database)
    ranking = RankingService(
        SqlAlchemyRankingRepository(database), RedisRankingStore(live_redis)
    )
    worker = BehaviorWorker(sql, live_redis, ranking)
    return sql, ranking, worker


@pytest.mark.parametrize("kind", ["like", "favorite", "view"])
def test_transactional_capture(database, kind):
    sql = SqlBehaviorOutbox(database)
    if kind == "view":
        SqlAlchemyHistoryRepository(database, outbox=sql).record(1, ACTOR)
    else:
        SqlAlchemyReactionRepository(database, outbox=sql).set_state(
            1, ACTOR, kind, True
        )
    event = row(database)
    assert event["tenant_id"] == "team" and event["subject"] == "one"
    assert event["kind"] == kind and event["attempts"] == 0
    assert event["completed_at"] is None


@pytest.mark.parametrize("kind", ["like", "view"])
def test_outbox_failure_rolls_back_behavior(database, kind):
    sql = SqlBehaviorOutbox(database)
    outbox.drop(database)
    with pytest.raises(DatabaseOperationError):
        if kind == "view":
            SqlAlchemyHistoryRepository(database, outbox=sql).record(1, ACTOR)
        else:
            SqlAlchemyReactionRepository(database, outbox=sql).set_state(
                1, ACTOR, "like", True
            )
    with database.connect() as connection:
        assert (
            connection.execute(select(func.count()).select_from(history)).scalar() == 0
        )
        assert (
            connection.execute(select(func.count()).select_from(reactions)).scalar()
            == 0
        )


def test_missing_recipe_has_no_event(database):
    with pytest.raises(ResourceNotFoundError):
        SqlAlchemyHistoryRepository(
            database, outbox=SqlBehaviorOutbox(database)
        ).record(99, ACTOR)
    assert row(database) is None


def test_real_queue_updates_and_duplicate_is_skipped(database, live_redis):
    sql, ranking, worker = stack(database, live_redis)
    SqlAlchemyReactionRepository(database, outbox=sql).set_state(1, ACTOR, "like", True)
    worker.run_once()
    event = row(database)
    assert event["completed_at"] is not None
    page = ranking.read("team", "popular")
    assert page.source == "redis" and page.items[0].score == 1
    ranking.refresh_tenant = Mock(
        side_effect=AssertionError("Duplicate must not refresh")
    )
    live_redis.xadd(STREAM, {"event_id": event["event_id"]})
    worker.run_once()
    ranking.refresh_tenant.assert_not_called()
    assert live_redis.xpending(STREAM, GROUP)["pending"] == 0
    assert live_redis.xlen(STREAM) == 0


def test_out_of_order_cancel_clears_empty_tenant(database, live_redis):
    sql, ranking, worker = stack(database, live_redis)
    repo = SqlAlchemyReactionRepository(database, outbox=sql)
    repo.set_state(1, ACTOR, "like", True)
    worker.run_once()
    assert ranking.read("team", "popular").items
    repo.set_state(1, ACTOR, "like", False)
    with database.connect() as connection:
        ids = list(
            connection.execute(
                select(outbox.c.event_id).order_by(outbox.c.created_at.desc())
            ).scalars()
        )
    worker._ensure_group()
    for event_id in ids:
        live_redis.xadd(STREAM, {"event_id": event_id})
    worker.run_once()
    assert ranking.read("team", "popular").source == "redis"
    assert ranking.read("team", "popular").items == ()


def test_redis_outage_does_not_rollback_user_action(database):
    sql = SqlBehaviorOutbox(database)
    SqlAlchemyReactionRepository(database, outbox=sql).set_state(1, ACTOR, "like", True)
    client = Mock()
    client.xadd.side_effect = ConnectionError("offline")
    worker = BehaviorWorker(sql, client, Mock())
    with pytest.raises(ConnectionError):
        worker.relay()
    assert sql.due(10) == (row(database)["event_id"],)
    assert SqlAlchemyReactionRepository(database).read(1, ACTOR).liked


def test_publish_crash_window_replays_without_double_count(database, live_redis):
    sql, ranking, worker = stack(database, live_redis)
    SqlAlchemyReactionRepository(database, outbox=sql).set_state(1, ACTOR, "like", True)
    worker._ensure_group()
    live_redis.xadd(STREAM, {"event_id": row(database)["event_id"]})
    worker.run_once()  # SQL still due: relay adds the same event ID again.
    assert ranking.read("team", "popular").items[0].score == 1
    assert row(database)["completed_at"] is not None


def test_lost_stream_republishes_sql_event(database, live_redis):
    sql, _, worker = stack(database, live_redis)
    SqlAlchemyHistoryRepository(database, outbox=sql).record(1, ACTOR)
    worker._ensure_group()
    worker.relay()
    live_redis.delete(STREAM)
    with database.begin() as connection:
        connection.execute(
            outbox.update().values(available_at=utcnow() - timedelta(seconds=1))
        )
    worker.run_once()
    assert row(database)["completed_at"] is not None


def test_crashed_consumer_pending_reclaimed(database, live_redis):
    sql, _, worker = stack(database, live_redis)
    SqlAlchemyHistoryRepository(database, outbox=sql).record(1, ACTOR)
    worker._ensure_group()
    worker.relay()
    pending = live_redis.xreadgroup(GROUP, "crashed", {STREAM: ">"})[0][1][0][0]
    live_redis.xclaim(STREAM, GROUP, "crashed", 0, [pending], idle=31000)
    worker.run_once()
    assert row(database)["completed_at"] is not None


@pytest.mark.parametrize("result", [False, RuntimeError("failure")])
def test_retry_dead_letter_and_operator_recovery(database, live_redis, result):
    sql, _, worker = stack(database, live_redis)
    worker._max_attempts = 2
    worker._ranking = Mock()
    if isinstance(result, Exception):
        worker._ranking.refresh_tenant.side_effect = result
    else:
        worker._ranking.refresh_tenant.return_value = result
    SqlAlchemyHistoryRepository(database, outbox=sql).record(1, ACTOR)
    worker.run_once()
    event = row(database)
    assert event["attempts"] == 1 and event["dead_at"] is None
    assert event["retry_at"] > utcnow()
    assert sql.claim(event["event_id"]) is None
    with database.begin() as connection:
        connection.execute(
            outbox.update().values(available_at=utcnow(), retry_at=utcnow())
        )
    worker.run_once()
    assert row(database)["dead_at"] is not None
    assert sql.due(10) == ()
    assert sql.requeue(event["event_id"])
    worker._ranking = Mock()
    worker._ranking.refresh_tenant.return_value = True
    worker.run_once()
    assert row(database)["completed_at"] is not None
    assert not sql.requeue(event["event_id"])


def test_sql_claim_exclusion_and_stale_token_fence(database):
    sql = SqlBehaviorOutbox(database)
    SqlAlchemyHistoryRepository(database, outbox=sql).record(1, ACTOR)
    event_id = row(database)["event_id"]
    first, tenant = sql.claim(event_id)
    assert tenant == "team" and sql.claim(event_id) is None
    with database.begin() as connection:
        connection.execute(
            outbox.update().values(lease_until=utcnow() - timedelta(seconds=1))
        )
    second, _ = sql.claim(event_id)
    sql.finish(event_id, first, None, 5)
    assert row(database)["completed_at"] is None
    sql.finish(event_id, second, None, 5)
    assert row(database)["completed_at"] is not None


@pytest.mark.parametrize(
    "fields", [{}, {"event_id": "bad"}, {"event_id": "bad", "tenant_id": "other"}]
)
def test_poison_envelope_isolated(database, live_redis, fields):
    _, _, worker = stack(database, live_redis)
    worker._ensure_group()
    live_redis.xadd(STREAM, fields or {"invalid": "x"})
    worker.run_once()
    assert live_redis.xlen(DEAD_STREAM) == 1
    assert live_redis.xpending(STREAM, GROUP)["pending"] == 0
    assert row(database) is None


def test_tenant_scope_comes_from_sql(database, live_redis):
    sql, ranking, worker = stack(database, live_redis)
    SqlAlchemyReactionRepository(database, outbox=sql).set_state(1, ACTOR, "like", True)
    worker.run_once()
    assert ranking.read("other", "popular").items == ()
    assert ranking.read("team", "popular").items[0].score == 1


def test_worker_lifecycle(database, live_redis):
    sql, _, worker = stack(database, live_redis)
    SqlAlchemyHistoryRepository(database, outbox=sql).record(1, ACTOR)

    async def run():
        worker.start()
        task = worker._task
        worker.start()
        assert task is worker._task
        for _ in range(100):
            if row(database)["completed_at"] is not None:
                break
            await asyncio.sleep(0.01)
        await worker.close()
        assert task.done() and worker._task is None

    asyncio.run(run())
    assert row(database)["completed_at"] is not None


def test_migration_roundtrip_and_preflight(database):
    outbox.drop(database)
    path = Path(
        "safemeal/infrastructure/persistence/migrations/versions/20261008_0012_behavior_outbox.py"
    )
    spec = importlib.util.spec_from_file_location("migration12", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with database.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert "behavior_outbox" in inspect(connection).get_table_names()
        with pytest.raises(RuntimeError, match="Unexpected"):
            migration.upgrade()
        migration.downgrade()
        assert "behavior_outbox" not in inspect(connection).get_table_names()


def test_refresh_then_sql_failure_replays_idempotently(
    database, live_redis, monkeypatch
):
    sql, ranking, worker = stack(database, live_redis)
    SqlAlchemyReactionRepository(database, outbox=sql).set_state(1, ACTOR, "like", True)
    original = sql.finish
    with monkeypatch.context() as patch:
        patch.setattr(
            sql, "finish", Mock(side_effect=RuntimeError("SQL commit unavailable"))
        )
        with pytest.raises(RuntimeError):
            worker.run_once()
    assert ranking.read("team", "popular").items[0].score == 1
    assert row(database)["completed_at"] is None
    assert live_redis.xpending(STREAM, GROUP)["pending"] == 1
    with database.begin() as connection:
        connection.execute(
            outbox.update().values(
                lease_until=utcnow() - timedelta(seconds=1), available_at=utcnow()
            )
        )
    assert sql.finish == original
    worker.run_once()
    assert row(database)["completed_at"] is not None
    assert ranking.read("team", "popular").items[0].score == 1


def test_duplicate_notifications_cannot_bypass_retry_delay(database, live_redis):
    sql, _, worker = stack(database, live_redis)
    worker._ranking = Mock()
    worker._ranking.refresh_tenant.return_value = False
    SqlAlchemyHistoryRepository(database, outbox=sql).record(1, ACTOR)
    worker.run_once()
    live_redis.xadd(STREAM, {"event_id": row(database)["event_id"]})
    worker.run_once()
    assert row(database)["attempts"] == 1
    assert worker._ranking.refresh_tenant.call_count == 1


def test_view_events_rebuild_distinct_viewer_statistics(database, live_redis):
    sql, ranking, worker = stack(database, live_redis)
    repo = SqlAlchemyHistoryRepository(database, outbox=sql)
    repo.record(1, ACTOR)
    repo.record(1, ACTOR)
    worker.run_once()
    assert ranking.read("team", "today").source == "redis"
    assert ranking.read("team", "today").items[0].score == 1


def test_bounded_batches(database, live_redis):
    sql, _, worker = stack(database, live_redis)
    worker._batch = 1
    repo = SqlAlchemyHistoryRepository(database, outbox=sql)
    for _ in range(3):
        repo.record(1, ACTOR)
    worker.run_once()
    with database.connect() as connection:
        assert (
            connection.execute(
                select(func.count())
                .select_from(outbox)
                .where(outbox.c.completed_at.is_not(None))
            ).scalar_one()
            == 1
        )
    worker.run_once()
    worker.run_once()
    assert sql.due(10) == ()
