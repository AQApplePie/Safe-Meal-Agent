"""Real Redis stop/start with production platform lifecycle and genuine JWT HTTP."""

from pathlib import Path
from uuid import uuid4
import json
import time

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select
from redis.exceptions import RedisError

from test_mysql_backend import services, docker, db, host_port  # noqa: F401
from safemeal.bootstrap.composition.platform_application import (
    create_platform_application,
)
from safemeal.config.platform import PlatformSettings
from safemeal.infrastructure.persistence.behavior_outbox import outbox
from safemeal.infrastructure.persistence.reaction_repository import reactions

pytestmark = [pytest.mark.integration, pytest.mark.testcontainers]
STABLE_REDIS_PORT = True
ENVIRONMENT_REPORT = "backend_operations_environment.json"
ROOT = Path(__file__).resolve().parents[2]


def test_real_redis_outage_durable_events_and_automatic_recovery(services):  # noqa: F811
    token = uuid4().hex
    redis_url = f"redis://127.0.0.1:{services.redis.connection_pool.connection_kwargs['port']}/0"
    config = PlatformSettings(
        DATABASE_URL=services.url.render_as_string(hide_password=False),
        METRICS_ENABLED=True,
        METRICS_TOKEN=token,
        METRICS_OUTBOX_SCRAPE_SECONDS=1,
        RECIPE_CACHE_URL=redis_url,
        RECIPE_RANKING_REDIS_URL=redis_url,
        BEHAVIOR_EVENT_REDIS_URL=redis_url,
        DEFAULT_TENANT_ID="operations-test",
        RECIPE_RANKING_REFRESH_SECONDS=1,
    )
    app = create_platform_application(config)
    stages = []
    redis_name = services.evidence["container_names"][1]
    stopped = False

    def sql_counts():
        with services.engine.connect() as conn:
            return {
                "facts": conn.execute(
                    select(func.count()).select_from(reactions)
                ).scalar_one(),
                "pending": conn.execute(
                    select(func.count())
                    .select_from(outbox)
                    .where(outbox.c.completed_at.is_(None), outbox.c.dead_at.is_(None))
                ).scalar_one(),
                "completed": conn.execute(
                    select(func.count())
                    .select_from(outbox)
                    .where(outbox.c.completed_at.is_not(None))
                ).scalar_one(),
            }

    try:
        with TestClient(app) as client:
            credentials = {
                "email": f"ops-{uuid4().hex}@example.test",
                "password": "OperationsDemo12345",
            }
            registered = client.post("/api/v1/auth/register", json=credentials)
            assert registered.status_code == 201
            headers = {"Authorization": "Bearer " + registered.json()["access_token"]}
            metrics_headers = {"Authorization": "Bearer " + token}
            assert client.get("/readyz").status_code == 200
            assert client.get("/api/v1/recipes/1").status_code == 200
            assert client.get("/metrics").status_code == 401
            assert client.get("/metrics", headers=headers).status_code == 401
            stages.append({"stage": "healthy", "sql": sql_counts()})
            docker("stop", "--time", "1", redis_name)
            stopped = True
            tick = time.monotonic()
            assert client.get("/livez").status_code == 200
            assert client.get("/readyz").status_code == 503
            time.sleep(
                1.05
            )  # Let bounded L1 expire; real SQL fallback, not warm local payload.
            assert client.get("/api/v1/recipes/1").status_code == 200
            for action in ("like", "favorite", "view"):
                response = client.put(f"/api/v1/recipes/1/{action}", headers=headers)
                assert response.status_code == 200
            time.sleep(1.05)
            metrics = client.get("/metrics", headers=metrics_headers)
            assert metrics.status_code == 200
            assert "safemeal_outbox_pending 3" in metrics.text
            assert "safemeal_outbox_collector_up 1" in metrics.text
            assert 'outcome="cycle_failed"' in metrics.text
            assert 'operation="redis_read_error"' in metrics.text
            assert sql_counts() == {"facts": 2, "pending": 3, "completed": 0}
            stages.append(
                {
                    "stage": "redis_down",
                    "elapsed_seconds": time.monotonic() - tick,
                    "sql": sql_counts(),
                    "metrics": metrics.text,
                }
            )
            docker("start", redis_name)
            stopped = False
            assert (
                host_port(redis_name, 6379)
                == services.redis.connection_pool.connection_kwargs["port"]
            )
            deadline = time.monotonic() + 20
            while True:
                try:
                    services.redis.ping()
                    if sql_counts()["completed"] == 3:
                        break
                except RedisError:
                    pass
                assert time.monotonic() < deadline, (
                    "Workers did not automatically recover"
                )
                time.sleep(0.1)
            assert client.get("/readyz").status_code == 200
            ranked = client.get(
                "/api/v1/recipes/rankings?mode=popular", headers=headers
            )
            assert ranked.status_code == 200 and ranked.json()["items"][0]["score"] == 2
            time.sleep(1.05)
            final = client.get("/metrics", headers=metrics_headers)
            assert (
                "safemeal_outbox_pending 0" in final.text
                and "safemeal_outbox_completed 3" in final.text
            )
            assert 'outcome="completed"} 3' in final.text
            assert credentials["email"] not in final.text and token not in final.text
            services.evidence["cases"]["redis_fault"] = (
                "actual stop/start; 3 durable events; automatic recovery"
            )
            stages.append(
                {
                    "stage": "recovered",
                    "sql": sql_counts(),
                    "metrics": final.text,
                    "ranking_score": 2,
                }
            )
    finally:
        if stopped:
            docker("start", redis_name)
        (ROOT / "evaluation_results/backend_operations_fault_drill.json").write_text(
            json.dumps(
                {
                    "stages": stages,
                    "method": "fixture-owned actual Redis stop/start; production app/lifespan/JWT; limiter disabled; no simulated SQL deadlines; automatic worker recovery",
                    "worker_tasks_closed": app.state.container._behavior_worker._task
                    is None,
                    "user_database_touched": False,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )


def test_real_dead_letter_operator_requeue_and_no_completed_replay(db):  # noqa: F811
    import os
    import subprocess
    import sys
    from safemeal.infrastructure.cache.ranking_store import RedisRankingStore
    from safemeal.infrastructure.messaging.behavior_worker import BehaviorWorker
    from safemeal.infrastructure.operations.metrics import RuntimeMetrics
    from safemeal.infrastructure.persistence.behavior_outbox import SqlBehaviorOutbox
    from safemeal.infrastructure.persistence.reaction_repository import (
        SqlAlchemyReactionRepository,
    )
    from safemeal.infrastructure.persistence.ranking_repository import (
        SqlAlchemyRankingRepository,
    )
    from safemeal.modules.interaction.application.ranking_service import RankingService
    from safemeal.modules.interaction.contracts.models import InteractionActor

    sql = SqlBehaviorOutbox(db.engine)
    metrics = RuntimeMetrics()
    store = RedisRankingStore(db.redis)
    ranking = RankingService(SqlAlchemyRankingRepository(db.engine), store)
    actor = InteractionActor(tenant_id="ops-dead", subject="test-operator")
    SqlAlchemyReactionRepository(db.engine, outbox=sql).set_state(
        1, actor, "like", True
    )
    worker = BehaviorWorker(
        sql, db.redis, ranking, max_attempts=1, observer=metrics.behavior
    )
    holder = store.acquire(actor.tenant_id)
    try:
        worker.run_once()
        dead = sql.metrics_snapshot()
        assert dead["dead"] == 1 and dead["failed_attempts"] == 1
    finally:
        store.release(actor.tenant_id, holder)
    with db.engine.connect() as conn:
        event_id = conn.execute(select(outbox.c.event_id)).scalar_one()
    env = {**os.environ, "PYTHONPATH": str(ROOT), "APP_ENV": "test"}
    command = [
        sys.executable,
        str(ROOT / "scripts/outbox_admin.py"),
        "requeue",
        event_id,
    ]
    repaired = subprocess.run(
        command, env=env, capture_output=True, text=True, timeout=10
    )
    assert repaired.returncode == 0 and json.loads(repaired.stdout) == {
        "requeued": True
    }
    worker.run_once()
    assert (
        sql.metrics_snapshot()["completed"] == 1 and sql.metrics_snapshot()["dead"] == 0
    )
    rejected = subprocess.run(
        command, env=env, capture_output=True, text=True, timeout=10
    )
    assert rejected.returncode == 2 and json.loads(rejected.stdout) == {
        "requeued": False
    }
    payload = metrics.render(sql.metrics_snapshot())
    assert (
        'outcome="refresh_failed"} 1' in payload and 'outcome="completed"} 1' in payload
    )
    db.evidence["cases"]["dead_letter_requeue"] = (
        "real ranking lease; CLI requeue; completed replay refused"
    )
    (ROOT / "evaluation_results/backend_operations_dead_letter.json").write_text(
        json.dumps(
            {
                "before_requeue": dead,
                "after_requeue": sql.metrics_snapshot(),
                "metrics": payload,
                "completed_replay_refused": True,
            },
            indent=2,
        )
        + "\n"
    )


@pytest.mark.asyncio
async def test_real_mysql_outage_scrape_omits_stale_gauges(db):  # noqa: F811
    import asyncio
    from safemeal.bootstrap.composition.platform_container import PlatformContainer
    from safemeal.infrastructure.persistence.behavior_outbox import SqlBehaviorOutbox

    container = PlatformContainer(
        PlatformSettings(
            DATABASE_URL=db.url.render_as_string(hide_password=False),
            METRICS_ENABLED=True,
            METRICS_OUTBOX_SCRAPE_SECONDS=1,
            BEHAVIOR_EVENT_REDIS_URL="redis://127.0.0.1:1",
            RECIPE_RANKING_REDIS_URL="redis://127.0.0.1:1",
        )
    )
    container._behavior_outbox = SqlBehaviorOutbox(db.engine)
    healthy = await container.get_outbox_metrics()
    assert healthy["collector_up"] == 1 and "pending" in healthy
    docker("stop", "--time", "1", db.evidence["container_names"][0])
    await asyncio.sleep(1.05)
    failed = await container.get_outbox_metrics()
    assert failed["collector_up"] == 0 and "pending" not in failed
    await container.shutdown()
    db.evidence["cases"]["mysql_collector_failure"] = (
        "actual MySQL stop; scrape up=0; stale backlog omitted"
    )
    (ROOT / "evaluation_results/backend_operations_mysql_failure.json").write_text(
        json.dumps(
            {
                "healthy": healthy,
                "database_down": failed,
                "method": "stop fixture-owned MySQL",
            },
            indent=2,
        )
        + "\n"
    )
