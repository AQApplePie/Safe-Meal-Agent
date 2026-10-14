"""Opt-in real MySQL/Redis acceptance. Always owns disposable containers; no external URL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace
from uuid import uuid4
import json
import multiprocessing
import os
import shutil
import socket
import subprocess
import time

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from redis import Redis
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError, OperationalError

from safemeal.config.platform import PlatformSettings
from safemeal.infrastructure.cache.ranking_store import RedisRankingStore
from safemeal.infrastructure.messaging.behavior_worker import (
    BehaviorWorker,
    GROUP,
    STREAM,
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
from safemeal.infrastructure.persistence.ranking_repository import (
    SqlAlchemyRankingRepository,
)
from safemeal.infrastructure.persistence.reaction_repository import (
    SqlAlchemyReactionRepository,
    reactions,
)
from safemeal.infrastructure.persistence.recipe_repository import recipes
from safemeal.infrastructure.persistence.transaction_retry import run_transaction
from safemeal.interfaces import build_api_router
from safemeal.interfaces.http.application import configure_http
from safemeal.interfaces.http.authentication import get_interaction_actor
from safemeal.interfaces.http.platform_dependencies import get_interaction_service
from safemeal.modules.interaction.application.interaction_service import (
    InteractionService,
)
from safemeal.modules.interaction.application.ranking_service import RankingService
from safemeal.modules.interaction.contracts.models import InteractionActor

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.integration, pytest.mark.testcontainers]
_ENABLED = (
    os.environ.get("RUN_MYSQL_INTEGRATION") == "1"
    or os.environ.get("RUN_TESTCONTAINERS") == "1"
)


def docker(*args, input=None):
    binary = shutil.which("docker") or "/usr/local/bin/docker"
    result = subprocess.run(
        [binary, *args], input=input, text=True, capture_output=True, timeout=120
    )
    if result.returncode:
        # Never echo commands: generated credentials are command arguments.
        raise RuntimeError("Disposable Docker operation failed: " + result.stderr[:500])
    return result.stdout.strip()


def host_port(name, port):
    mapping = json.loads(
        docker("inspect", "--format", "{{json .NetworkSettings.Ports}}", name)
    )
    return int(mapping[f"{port}/tcp"][0]["HostPort"])


@pytest.fixture(scope="module")
def services(tmp_path_factory, request):
    if not _ENABLED:
        pytest.skip(
            "set RUN_MYSQL_INTEGRATION=1 to create owned MySQL/Redis containers"
        )
    token = uuid4().hex[:12]
    mysql_name, redis_name = f"sm-mysql-it-{token}", f"sm-redis-it-{token}"
    redis_binding = "127.0.0.1::6379"
    if getattr(request.module, "STABLE_REDIS_PORT", False):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            redis_binding = f"127.0.0.1:{reservation.getsockname()[1]}:6379"
    password = uuid4().hex
    engine = client = None
    evidence = {"container_names": [mysql_name, redis_name], "cases": {}}
    try:
        docker(
            "run",
            "-d",
            "--name",
            mysql_name,
            "--label",
            "safemeal.test=mysql-integration",
            "--tmpfs",
            "/var/lib/mysql",
            "-p",
            "127.0.0.1::3306",
            "-e",
            f"MYSQL_ROOT_PASSWORD={password}",
            "-e",
            "MYSQL_ROOT_HOST=%",
            "-e",
            "MYSQL_DATABASE=recipe_db",
            "mysql:8.0",
        )
        docker(
            "run",
            "-d",
            "--name",
            redis_name,
            "--label",
            "safemeal.test=mysql-integration",
            "-p",
            redis_binding,
            "redis:7-alpine",
            "redis-server",
            "--save",
            "",
            "--appendonly",
            "no",
        )
        url = URL.create(
            "mysql+pymysql",
            username="root",
            password=password,
            host="127.0.0.1",
            port=host_port(mysql_name, 3306),
            database="recipe_db",
        )
        engine = create_engine(
            url,
            pool_size=32,
            max_overflow=0,
            pool_pre_ping=True,
            connect_args={
                "connect_timeout": 2,
                "init_command": "SET SESSION innodb_lock_wait_timeout=1",
            },
        )
        client = Redis(
            host="127.0.0.1",
            port=host_port(redis_name, 6379),
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=2,
        )
        deadline = time.monotonic() + 90
        while True:
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                assert client.ping()
                break
            except Exception:
                if time.monotonic() > deadline:
                    pytest.fail("Owned MySQL/Redis did not become ready")
                time.sleep(0.25)
        for filename in ("init_mysql.sql", "insert_sample_data.sql"):
            docker(
                "exec",
                "-i",
                mysql_name,
                "mysql",
                "-uroot",
                f"-p{password}",
                input=(ROOT / "data/mysql" / filename).read_text(),
            )
        temporary = tmp_path_factory.mktemp("mysql-integration")
        previous = {
            key: os.environ.get(key)
            for key in ("DATABASE_URL", "SAFEMEAL_ENV_FILE", "APP_ENV")
        }
        os.environ.update(
            DATABASE_URL=url.render_as_string(hide_password=False),
            SAFEMEAL_ENV_FILE=str(temporary / "absent.env"),
            APP_ENV="test",
        )
        try:
            command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
            with engine.connect() as conn:
                evidence.update(
                    mysql_version=conn.execute(text("SELECT VERSION()")).scalar_one(),
                    isolation=conn.execute(
                        text("SELECT @@transaction_isolation")
                    ).scalar_one(),
                    lock_wait_seconds=conn.execute(
                        text("SELECT @@innodb_lock_wait_timeout")
                    ).scalar_one(),
                    migration_head=conn.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar_one(),
                    recipe_count=conn.execute(
                        select(func.count()).select_from(recipes)
                    ).scalar_one(),
                    redis_version=client.info("server")["redis_version"],
                )
            yield SimpleNamespace(
                engine=engine, redis=client, url=url, evidence=evidence
            )
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    finally:
        if client is not None:
            client.close()
        if engine is not None:
            engine.dispose()
        for name in (mysql_name, redis_name):
            try:
                docker("rm", "-f", name)
                evidence.setdefault("cleanup_removed", {})[name] = True
            except RuntimeError:
                evidence.setdefault("cleanup_removed", {})[name] = False
        evidence["cleanup_attempted"] = True
        (
            ROOT
            / "evaluation_results"
            / getattr(
                request.module,
                "ENVIRONMENT_REPORT",
                "mysql_integration_environment.json",
            )
        ).write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")


@pytest.fixture
def db(services):
    # Only the fixture-created database and Redis above; never a configured server.
    with services.engine.begin() as conn:
        for table in (outbox, reactions, history):
            conn.execute(table.delete())
    services.redis.flushdb()
    return services


def actor(subject="alice", tenant="team"):
    return InteractionActor(tenant_id=tenant, subject=subject)


def count(db, table):
    with db.engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()


def concurrent(n, operation):
    barrier = Barrier(n)

    def work(index):
        barrier.wait(timeout=10)
        return operation(index)

    with ThreadPoolExecutor(max_workers=n) as executor:
        return list(executor.map(work, range(n)))


def event_row(db, event_id):
    with db.engine.connect() as conn:
        return (
            conn.execute(select(outbox).where(outbox.c.event_id == event_id))
            .mappings()
            .one()
        )


def test_full_migration_roundtrip_preserves_catalog(db):
    config = Config(str(ROOT / "alembic.ini"))
    command.downgrade(config, "base")
    assert "recipe_reactions" not in inspect(db.engine).get_table_names()
    assert count(db, recipes) == 70
    command.upgrade(config, "head")
    with db.engine.connect() as conn:
        assert (
            conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "20261009_0014"
        )
        assert (
            conn.execute(
                text("SHOW COLUMNS FROM recipe_reactions WHERE Field='subject'")
            ).first()
            is not None
        )
    assert count(db, recipes) == 70
    assert "ix_recipe_reactions_favorites" in {
        i["name"] for i in inspect(db.engine).get_indexes("recipe_reactions")
    }
    db.evidence["cases"]["migration_roundtrip"] = (
        "head -> base -> head; 70 catalog rows preserved"
    )


@pytest.mark.parametrize("kind", ["like", "favorite"])
def test_same_user_concurrent_enable_and_cancel(db, kind):
    repo = SqlAlchemyReactionRepository(db.engine, outbox=SqlBehaviorOutbox(db.engine))
    added = concurrent(24, lambda _: repo.set_state(1, actor(), kind, True))
    assert count(db, reactions) == 1
    assert all(getattr(row, f"{kind}_count") == 1 for row in added)
    removed = concurrent(24, lambda _: repo.set_state(1, actor(), kind, False))
    assert count(db, reactions) == 0
    assert all(getattr(row, f"{kind}_count") == 0 for row in removed)
    assert count(db, outbox) == 48
    db.evidence["cases"][f"same_user_{kind}"] = (
        "24 concurrent enable + 24 cancel; one fact then zero; 48 committed notifications"
    )


def test_different_users_counts_are_serialized_under_repeatable_read(db):
    repo = SqlAlchemyReactionRepository(db.engine)
    results = concurrent(
        24, lambda i: repo.set_state(1, actor(f"user-{i}"), "like", True)
    )
    assert sorted(row.like_count for row in results) == list(range(1, 25))
    assert repo.read(1, actor()).like_count == count(db, reactions) == 24
    concurrent(24, lambda i: repo.set_state(1, actor(f"user-{i}"), "like", False))
    assert repo.read(1, actor()).like_count == 0
    db.evidence["cases"]["different_users"] = (
        "24 concurrent users; returned counts 1..24 under REPEATABLE-READ; cancel to zero"
    )


def test_binary_identity_unique_constraint_and_foreign_key(db):
    repo = SqlAlchemyReactionRepository(db.engine)
    for tenant, subject in [("team", "alice"), ("team", "Alice"), ("Team", "alice")]:
        repo.set_state(1, actor(subject, tenant), "like", True)
    assert count(db, reactions) == 3
    assert repo.read(1, actor()).like_count == 2
    with pytest.raises(IntegrityError):
        with db.engine.begin() as conn:
            conn.execute(
                reactions.insert().values(
                    tenant_id="team", subject="alice", recipe_id=1, kind="like"
                )
            )
    with pytest.raises(IntegrityError):
        with db.engine.begin() as conn:
            conn.execute(
                reactions.insert().values(
                    tenant_id="team", subject="alice", recipe_id=9999999, kind="like"
                )
            )
    db.evidence["cases"]["constraints"] = (
        "case-sensitive identity, unique PK, FK violations rejected by MySQL"
    )


@pytest.mark.parametrize("kind", ["like", "favorite", "view"])
def test_behavior_and_outbox_rollback_together(db, kind):
    class FailingOutbox(SqlBehaviorOutbox):
        def append(self, *args, **kwargs):
            super().append(*args, **kwargs)
            raise RuntimeError("Injected failure after outbox INSERT")

    sql = FailingOutbox(db.engine)
    with pytest.raises(RuntimeError, match="after outbox"):
        if kind == "view":
            SqlAlchemyHistoryRepository(db.engine, outbox=sql).record(1, actor())
        else:
            SqlAlchemyReactionRepository(db.engine, outbox=sql).set_state(
                1, actor(), kind, True
            )
    assert count(db, reactions) == count(db, history) == count(db, outbox) == 0
    db.evidence["cases"][f"rollback_{kind}"] = (
        "exception after behavior + outbox INSERT; both rolled back"
    )


def test_history_concurrent_dedup_and_microsecond_order(db):
    repo = SqlAlchemyHistoryRepository(db.engine, outbox=SqlBehaviorOutbox(db.engine))
    concurrent(24, lambda _: repo.record(1, actor()))
    assert count(db, history) == 1 and count(db, outbox) == 24
    repo.record(2, actor())
    rows = repo.list_recent(actor(), 10, None)
    assert [row.recipe_id for row in rows] == [2, 1]
    db.evidence["cases"]["history"] = (
        "24 concurrent views -> one history fact; newer recipe first"
    )


def test_real_lock_timeout_retries_then_succeeds_without_duplicate_event(db):
    sql = SqlBehaviorOutbox(db.engine)
    repo = SqlAlchemyReactionRepository(db.engine, outbox=sql)
    timed_out = Event()
    errors = []

    def on_error(context):
        code = context.original_exception.args[0]
        errors.append(code)
        if code == 1205:
            timed_out.set()

    event.listen(db.engine, "handle_error", on_error)
    try:
        with db.engine.connect() as blocker:
            transaction = blocker.begin()
            blocker.execute(
                select(recipes.c.id).where(recipes.c.id == 1).with_for_update()
            )
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(repo.set_state, 1, actor(), "like", True)
                assert timed_out.wait(5), "MySQL did not produce a real lock timeout"
                transaction.rollback()
                assert future.result(timeout=5).liked
    finally:
        event.remove(db.engine, "handle_error", on_error)
    assert errors == [1205]
    assert count(db, reactions) == count(db, outbox) == 1
    db.evidence["cases"]["lock_retry_success"] = {
        "mysql_codes": errors,
        "committed_events": 1,
    }


def test_exhausted_lock_retries_return_http_503_and_rollback(db):
    repo = SqlAlchemyReactionRepository(
        db.engine, outbox=SqlBehaviorOutbox(db.engine), transaction_attempts=2
    )
    application = FastAPI()
    config = PlatformSettings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL=db.url.render_as_string(hide_password=False),
        REDIS_RATE_LIMIT_URL=None,
        BEHAVIOR_EVENT_REDIS_URL=None,
    )
    application.state.settings = config
    configure_http(application, config)
    application.include_router(build_api_router(include_agent=False), prefix="/api/v1")
    application.dependency_overrides[get_interaction_actor] = lambda: actor()
    application.dependency_overrides[get_interaction_service] = lambda: (
        InteractionService(repo)
    )
    errors = []

    def on_error(context):
        errors.append(context.original_exception.args[0])

    event.listen(db.engine, "handle_error", on_error)
    try:
        with db.engine.connect() as blocker:
            transaction = blocker.begin()
            blocker.execute(
                select(recipes.c.id).where(recipes.c.id == 1).with_for_update()
            )
            with TestClient(application) as client:
                response = client.put("/api/v1/recipes/1/like")
            transaction.rollback()
    finally:
        event.remove(db.engine, "handle_error", on_error)
    assert response.status_code == 503
    assert response.json() == {
        "error": "database_unavailable",
        "message": "Database is temporarily unavailable",
    }
    assert errors == [1205, 1205]
    assert count(db, reactions) == count(db, outbox) == 0
    assert repo.set_state(1, actor(), "like", True).liked
    db.evidence["cases"]["lock_retry_exhausted"] = {
        "mysql_codes": errors,
        "http_status": 503,
        "client_retry_after_release": "passed",
    }


def test_real_deadlock_retries_entire_transaction(db):
    barrier = Barrier(2)
    errors = []

    def on_error(context):
        errors.append(context.original_exception.args[0])

    event.listen(db.engine, "handle_error", on_error)
    sql = SqlBehaviorOutbox(db.engine)

    def work(index):
        attempts = 0

        def operation(conn):
            nonlocal attempts
            attempts += 1
            first, second = (1, 2) if index == 0 else (2, 1)
            conn.execute(
                select(recipes.c.id).where(recipes.c.id == first).with_for_update()
            )
            sql.append(conn, actor(f"deadlock-{index}"), first, "view")
            if attempts == 1:
                barrier.wait(timeout=5)
            conn.execute(
                select(recipes.c.id).where(recipes.c.id == second).with_for_update()
            )

        run_transaction(db.engine, operation)
        return attempts

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            attempts = list(executor.map(work, range(2)))
    finally:
        event.remove(db.engine, "handle_error", on_error)
    assert errors == [1213]
    assert sorted(attempts) == [1, 2]
    assert count(db, outbox) == 2
    db.evidence["cases"]["deadlock"] = {
        "mysql_codes": errors,
        "attempts": sorted(attempts),
        "committed_events": 2,
    }


def test_sql_claim_two_instances_and_expired_token_fencing(db):
    sql = SqlBehaviorOutbox(db.engine)
    SqlAlchemyHistoryRepository(db.engine, outbox=sql).record(1, actor())
    with db.engine.connect() as conn:
        event_id = conn.execute(select(outbox.c.event_id)).scalar_one()
    claims = concurrent(16, lambda _: SqlBehaviorOutbox(db.engine).claim(event_id))
    winners = [claim for claim in claims if claim is not None]
    assert len(winners) == 1
    old_token, _ = winners[0]
    with db.engine.begin() as conn:
        conn.execute(
            outbox.update()
            .where(outbox.c.event_id == event_id)
            .values(lease_until=utcnow() - timedelta(seconds=2))
        )
    new_token, _ = SqlBehaviorOutbox(db.engine).claim(event_id)
    assert new_token != old_token
    sql.finish(event_id, old_token, None, 5)
    assert event_row(db, event_id)["completed_at"] is None
    sql.finish(event_id, new_token, None, 5)
    assert event_row(db, event_id)["completed_at"] is not None
    db.evidence["cases"]["sql_lease"] = (
        "16 concurrent claims -> one winner; expired lease recovered; old token rejected"
    )


def _consumer_process(url, port, ready, start, results):
    engine = create_engine(url, pool_pre_ping=True)
    client = Redis(host="127.0.0.1", port=port, decode_responses=True, socket_timeout=2)
    try:
        ranking = RankingService(
            SqlAlchemyRankingRepository(engine), RedisRankingStore(client)
        )
        worker = BehaviorWorker(SqlBehaviorOutbox(engine), client, ranking)
        ready.put("ready")
        if not start.wait(15):
            raise TimeoutError("Consumer start gate timed out")
        worker.run_once()
        results.put(
            {"status": "passed", "pid": os.getpid(), "consumer": worker._consumer}
        )
    except Exception as exc:
        results.put({"status": "failed", "error": type(exc).__name__})
    finally:
        client.close()
        engine.dispose()


def _two_consumer_processes(db):
    context = multiprocessing.get_context("spawn")
    ready, results, start = context.Queue(), context.Queue(), context.Event()
    port = db.redis.connection_pool.connection_kwargs["port"]
    processes = [
        context.Process(
            target=_consumer_process,
            args=(
                db.url.render_as_string(hide_password=False),
                port,
                ready,
                start,
                results,
            ),
        )
        for _ in range(2)
    ]
    try:
        for process in processes:
            process.start()
        assert [ready.get(timeout=20) for _ in range(2)] == ["ready", "ready"]
        start.set()
        outcomes = [results.get(timeout=20) for _ in range(2)]
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
        assert all(row["status"] == "passed" for row in outcomes), outcomes
        assert len({row["pid"] for row in outcomes}) == 2
        return outcomes
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        for queue in (ready, results):
            queue.close()
            queue.join_thread()


def test_two_consumers_deduplicate_real_mysql_redis_and_reclaim_crash(db):
    sql = SqlBehaviorOutbox(db.engine)
    repo = SqlAlchemyReactionRepository(db.engine, outbox=sql)
    repo.set_state(1, actor(), "like", True)
    with db.engine.connect() as conn:
        event_id = conn.execute(select(outbox.c.event_id)).scalar_one()
    rankings = [
        RankingService(
            SqlAlchemyRankingRepository(db.engine), RedisRankingStore(db.redis)
        )
        for _ in range(2)
    ]
    workers = [
        BehaviorWorker(SqlBehaviorOutbox(db.engine), db.redis, ranking)
        for ranking in rankings
    ]
    workers[0]._ensure_group()
    for _ in range(12):
        db.redis.xadd(STREAM, {"event_id": event_id})
    process_results = _two_consumer_processes(db)
    assert event_row(db, event_id)["completed_at"] is not None
    page = rankings[0].read("team", "popular")
    assert page.source == "redis" and page.items[0].score == 1
    assert db.redis.xpending(STREAM, GROUP)["pending"] == 0
    repo.set_state(1, actor(), "favorite", True)
    workers[0].relay()
    pending = db.redis.xreadgroup(GROUP, "crashed", {STREAM: ">"})[0][1][0][0]
    # Advance only fixture-owned PEL idle time; do not sleep 30 seconds.
    db.redis.xclaim(STREAM, GROUP, "crashed", 0, [pending], idle=31000)
    workers[1].run_once()
    assert count(db, outbox) == 2
    with db.engine.connect() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(outbox)
                .where(outbox.c.completed_at.is_not(None))
            ).scalar_one()
            == 2
        )
    assert rankings[1].read("team", "popular").items[0].score == 2
    assert db.redis.xpending(STREAM, GROUP)["pending"] == 0
    db.evidence["cases"]["consumers"] = {
        "processes": process_results,
        "result": "two independent processes; 12 duplicate envelopes; one score; crashed PEL reclaimed; score rebuilt to 2",
    }


def test_retry_dead_letter_and_explicit_recovery_on_real_services(db):
    sql = SqlBehaviorOutbox(db.engine)
    SqlAlchemyHistoryRepository(db.engine, outbox=sql).record(1, actor())
    with db.engine.connect() as conn:
        event_id = conn.execute(select(outbox.c.event_id)).scalar_one()
    ranking = RankingService(
        SqlAlchemyRankingRepository(db.engine), RedisRankingStore(db.redis)
    )
    store = ranking._store
    token = store.acquire("team")
    assert token is not None
    worker = BehaviorWorker(sql, db.redis, ranking, max_attempts=2)
    worker.run_once()
    assert event_row(db, event_id)["attempts"] == 1
    db.redis.xadd(STREAM, {"event_id": event_id})
    worker.run_once()
    assert event_row(db, event_id)["attempts"] == 1
    with db.engine.begin() as conn:
        conn.execute(
            outbox.update()
            .where(outbox.c.event_id == event_id)
            .values(
                available_at=utcnow() - timedelta(seconds=2),
                retry_at=utcnow() - timedelta(seconds=2),
            )
        )
    worker.run_once()
    assert event_row(db, event_id)["dead_at"] is not None
    store.release("team", token)
    assert sql.requeue(event_id)
    worker.run_once()
    assert event_row(db, event_id)["completed_at"] is not None
    assert not sql.requeue(event_id)
    db.evidence["cases"]["dead_letter"] = (
        "real ranking lease contention; backoff not bypassed by duplicates; 2 failures -> SQL dead letter; requeue completes"
    )


def test_connection_loss_is_not_automatically_replayed(db):
    attempts = 0
    sql = SqlBehaviorOutbox(db.engine)

    def operation(conn):
        nonlocal attempts
        attempts += 1
        sql.append(conn, actor(), 1, "view")
        connection_id = int(conn.execute(text("SELECT CONNECTION_ID()")).scalar_one())
        # Root only in this owned fixture. Kill this operation's connection,
        # never a user-configured connection or another service.
        with db.engine.connect() as killer:
            killer.execute(text(f"KILL CONNECTION {connection_id}"))
        conn.execute(text("SELECT 1"))

    with pytest.raises(OperationalError) as failure:
        run_transaction(db.engine, operation)
    assert failure.value.orig.args[0] == 2013
    assert attempts == 1
    assert count(db, outbox) == 0
    db.evidence["cases"]["connection_loss"] = {
        "mysql_code": 2013,
        "attempts": attempts,
        "committed_events": 0,
    }


def test_outbox_subsecond_deadline_is_not_rounded_into_future(db, monkeypatch):
    from datetime import datetime
    import safemeal.infrastructure.persistence.behavior_outbox as module

    fixed_now = datetime(2026, 10, 9, 12, 0, 0, 900000)
    monkeypatch.setattr(module, "utcnow", lambda: fixed_now)
    sql = SqlBehaviorOutbox(db.engine)
    SqlAlchemyHistoryRepository(db.engine, outbox=sql).record(1, actor())
    with db.engine.connect() as conn:
        event_id = conn.execute(select(outbox.c.event_id)).scalar_one()
    stored = event_row(db, event_id)["retry_at"]
    db.evidence["cases"]["timestamp_precision"] = {
        "written": fixed_now.isoformat(),
        "stored": stored.isoformat(),
    }
    assert stored == fixed_now
    assert sql.claim(event_id) is not None


def test_precision_upgrade_preserves_existing_events(db):
    config = Config(str(ROOT / "alembic.ini"))
    command.downgrade(config, "20261008_0012")
    try:
        SqlAlchemyHistoryRepository(
            db.engine, outbox=SqlBehaviorOutbox(db.engine)
        ).record(1, actor())
        with db.engine.connect() as conn:
            event_id = conn.execute(select(outbox.c.event_id)).scalar_one()
        before = dict(event_row(db, event_id))
    finally:
        command.upgrade(config, "head")
    assert dict(event_row(db, event_id)) == before
    columns = {c["name"]: c for c in inspect(db.engine).get_columns("behavior_outbox")}
    for name in (
        "created_at",
        "available_at",
        "retry_at",
        "lease_until",
        "completed_at",
        "dead_at",
    ):
        assert columns[name]["type"].fsp == 6
    db.evidence["cases"]["existing_event_upgrade"] = (
        "0012 -> 0013; all six DATETIME(6); existing event fields unchanged"
    )


def test_composition_applies_configured_mysql_lock_timeout(db):
    import asyncio
    from safemeal.bootstrap.composition.platform_container import PlatformContainer
    from safemeal.infrastructure.persistence.database import dispose_engine, get_engine

    dispose_engine()
    config = PlatformSettings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL=db.url.render_as_string(hide_password=False),
        DB_LOCK_WAIT_TIMEOUT_SECONDS=2,
        DB_TRANSACTION_MAX_ATTEMPTS=1,
        RECIPE_CACHE_URL=None,
        REDIS_RATE_LIMIT_URL=None,
        RECIPE_RANKING_REDIS_URL=None,
        BEHAVIOR_EVENT_REDIS_URL=None,
    )
    container = PlatformContainer(config)
    try:
        with get_engine().connect() as conn:
            assert (
                conn.execute(text("SELECT @@innodb_lock_wait_timeout")).scalar_one()
                == 2
            )
        service = container.get_interaction_service()
        with db.engine.connect() as blocker:
            transaction = blocker.begin()
            blocker.execute(
                select(recipes.c.id).where(recipes.c.id == 1).with_for_update()
            )
            from safemeal.shared.exceptions import DatabaseUnavailableError

            with pytest.raises(DatabaseUnavailableError):
                service.set_state(1, actor(), "like", True)
            transaction.rollback()
        assert service.set_state(1, actor(), "like", True).liked
    finally:
        asyncio.run(container.shutdown())
    db.evidence["cases"]["composition"] = (
        "real session lock_wait=2; one-attempt contention fails; released lock succeeds"
    )


def test_history_current_read_after_noop_upsert_in_old_rr_snapshot(db):
    from threading import current_thread

    paused, release = Event(), Event()

    def pause_insert(conn, cursor, statement, parameters, context, executemany):
        if current_thread().name.startswith("stale-reader") and statement.startswith(
            "INSERT INTO recipe_view_history"
        ):
            paused.set()
            assert release.wait(5)

    event.listen(db.engine, "before_cursor_execute", pause_insert)
    future_time = utcnow() + timedelta(days=1)
    repo = SqlAlchemyHistoryRepository(db.engine, outbox=SqlBehaviorOutbox(db.engine))
    try:
        with ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="stale-reader"
        ) as pool:
            future = pool.submit(repo.record, 1, actor())
            try:
                assert paused.wait(5)
                # Another transaction commits after the first recipe SELECT
                # established an RR snapshot. Its later timestamp makes the
                # first transaction's GREATEST upsert an actual no-op.
                with db.engine.begin() as conn:
                    conn.execute(
                        history.insert().values(
                            tenant_id="team",
                            subject="alice",
                            recipe_id=1,
                            last_viewed_at=future_time,
                        )
                    )
                release.set()
                result = future.result(timeout=5)
            finally:
                release.set()
    finally:
        event.remove(db.engine, "before_cursor_execute", pause_insert)
    assert result.last_viewed_at.replace(tzinfo=None) == future_time
    assert count(db, history) == count(db, outbox) == 1
    db.evidence["cases"]["rr_history_snapshot"] = (
        "old RR snapshot + concurrent insert + no-op UPSERT; current read returns committed history; one outbox event"
    )
