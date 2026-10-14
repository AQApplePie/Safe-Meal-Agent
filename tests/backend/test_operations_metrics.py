"""Metric accuracy, bounded labels, protection and durable queue gauges."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy import select

from test_recipe_browsing import (
    catalog as catalog,
    live_redis as live_redis,
    redis_server as redis_server,
)
from test_behavior_events import database as database
from safemeal.config.platform import PlatformSettings
from safemeal.bootstrap.composition.platform_container import PlatformContainer
from safemeal.infrastructure.operations.metrics import RuntimeMetrics
from safemeal.infrastructure.cache.recipe_repository import CachedRecipeRepository
from safemeal.infrastructure.persistence.behavior_outbox import (
    SqlBehaviorOutbox,
    outbox,
    utcnow,
)
from safemeal.interfaces.http.application import configure_http
from safemeal.modules.interaction.contracts.models import InteractionActor
from safemeal.shared.exceptions import DatabaseOperationError


def test_threaded_counters_and_histogram():
    metrics = RuntimeMetrics()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda _: metrics.http("GET", "/recipes/{id}", 200, 0.02), range(100)
            )
        )
    payload = metrics.render({"collector_up": 1.0})
    assert (
        'safemeal_http_requests_total{method="GET",route="/recipes/{id}",status="200"} 100'
        in payload
    )
    assert 'status="200",le="0.01"} 0' in payload
    assert 'status="200",le="0.025"} 100' in payload
    assert 'status="200",le="+Inf"} 100' in payload


def test_http_status_templates_and_metrics_protection():
    config = PlatformSettings(
        DATABASE_URL="sqlite://", METRICS_ENABLED=True, METRICS_TOKEN="m" * 32
    )
    app = FastAPI()
    configure_http(app, config)

    @app.get("/recipes/{recipe_id}")
    def read(recipe_id: int):
        return {"id": recipe_id}

    @app.get("/failure")
    def fail():
        raise DatabaseOperationError()

    @app.get("/crash")
    def crash():
        raise RuntimeError("controlled test failure")

    with TestClient(app, raise_server_exceptions=False) as client:
        for n in range(20):
            assert client.get(f"/recipes/{n}").status_code == 200
            assert client.get(f"/missing-{uuid4().hex}").status_code == 404
        assert client.get("/failure").status_code == 503
        assert client.get("/crash").status_code == 500
        assert client.get("/metrics").status_code == 401
        assert (
            client.get(
                "/metrics", headers={"Authorization": "Bearer wrong"}
            ).status_code
            == 401
        )
        response = client.get(
            "/metrics", headers={"Authorization": "Bearer " + "m" * 32}
        )
        assert (
            response.status_code == 200
            and response.headers["cache-control"] == "no-store"
        )
        payload = response.text
        assert "/recipes/{recipe_id}" in payload and "__unmatched__" in payload
        assert "/missing-" not in payload and "/metrics" not in payload
        assert 'status="500"' in payload and 'status="503"' in payload
        assert 'route="/recipes/{recipe_id}",status="200"} 20' in payload


def test_metrics_disabled_and_production_validation():
    app = FastAPI()
    configure_http(
        app, PlatformSettings(DATABASE_URL="sqlite://", METRICS_ENABLED=False)
    )
    assert TestClient(app).get("/metrics").status_code == 404
    with pytest.raises(ValidationError, match="production metrics require"):
        PlatformSettings(
            DATABASE_URL="mysql+pymysql://test:test@localhost/test",
            APP_ENV="production",
            AUTH_JWT_SECRET="j" * 32,
            CORS_ORIGINS="https://example.test",
            METRICS_ENABLED=True,
        )
    assert (
        PlatformSettings(DATABASE_URL="sqlite://", METRICS_TOKEN="").METRICS_TOKEN
        is None
    )


def test_cache_counts_logical_requests_by_source(catalog, live_redis):  # noqa: F811
    metrics = RuntimeMetrics()
    cache = CachedRecipeRepository(catalog[1], live_redis, observer=metrics.recipe_read)
    assert cache.get(1).id == 1
    assert cache.get(1).id == 1
    redis_only = CachedRecipeRepository(
        catalog[1], live_redis, local_ttl_seconds=0, observer=metrics.recipe_read
    )
    assert redis_only.get(1).id == 1
    payload = metrics.render({})
    for source in ("database", "l1", "redis"):
        assert f'kind="detail",source="{source}"}} 1' in payload
    # Observation failures never change cache return values.
    bad = Mock(side_effect=RuntimeError("observer unavailable"))
    assert CachedRecipeRepository(catalog[1], live_redis, observer=bad).get(1).id == 1
    live_redis.set("safemeal:recipes:v1:detail:2", "broken-json")
    assert redis_only.get(2).id == 2
    assert 'operation="decode_error"} 2' in metrics.render({})


def test_durable_outbox_gauges_and_requeue(database):  # noqa: F811
    sql = SqlBehaviorOutbox(database)
    assert sql.metrics_snapshot()["pending"] == 0
    with database.begin() as conn:
        event_id = sql.append(
            conn,
            InteractionActor(tenant_id="private-tenant", subject="private-user"),
            1,
            "like",
            True,
        )
        conn.execute(
            outbox.update().values(created_at=utcnow() - timedelta(seconds=10))
        )
    first = sql.metrics_snapshot()
    assert first["pending"] == 1 and first["oldest_pending_age_seconds"] >= 10
    token, _ = sql.claim(event_id)
    assert sql.metrics_snapshot()["leased"] == 1
    sql.finish(event_id, token, "ranking-unavailable", 1)
    dead = sql.metrics_snapshot()
    assert dead["dead"] == 1 and dead["pending"] == 0 and dead["failed_attempts"] == 1
    assert sql.requeue(event_id)
    retried = sql.metrics_snapshot()
    assert (
        retried["dead"] == 0
        and retried["pending"] == 1
        and retried["failed_attempts"] == 0
    )
    assert "private" not in RuntimeMetrics().render(retried)
    with database.connect() as conn:
        assert conn.execute(select(outbox.c.completed_at)).scalar_one() is None


@pytest.mark.asyncio
async def test_collector_failure_omits_stale_gauges_and_singleflight():
    config = PlatformSettings(
        DATABASE_URL="sqlite://",
        METRICS_ENABLED=True,
        BEHAVIOR_EVENT_REDIS_URL="redis://127.0.0.1:1",
        RECIPE_RANKING_REDIS_URL="redis://127.0.0.1:1",
    )
    container = PlatformContainer(config)
    collector = Mock(return_value={"pending": 3.0})
    container._behavior_outbox = Mock(metrics_snapshot=collector)
    import asyncio

    values = await asyncio.gather(*(container.get_outbox_metrics() for _ in range(10)))
    assert all(value["pending"] == 3 for value in values) and collector.call_count == 1
    container._metrics_checked_at = 0
    collector.side_effect = RuntimeError("database offline")
    failed = await container.get_outbox_metrics()
    assert failed["collector_up"] == 0 and "pending" not in failed
    await container.shutdown()


def test_rate_limiter_failure_is_503_and_scrape_is_exempt(monkeypatch):
    from redis.exceptions import ConnectionError
    from safemeal.interfaces.http import request_middleware

    class OfflineBucket:
        async def acquire(self, *args, **kwargs):
            raise ConnectionError("controlled Redis failure")

        async def close(self):
            pass

    monkeypatch.setattr(
        request_middleware, "create_rate_limiter", lambda _: OfflineBucket()
    )
    app = FastAPI()
    configure_http(
        app,
        PlatformSettings(
            DATABASE_URL="sqlite://",
            REDIS_RATE_LIMIT_URL="redis://127.0.0.1:1",
            METRICS_ENABLED=True,
        ),
    )

    @app.get("/business")
    def business():
        pytest.fail("Fail-closed limiter must not run the business handler")

    with TestClient(app) as client:
        response = client.get("/business")
        assert response.status_code == 503 and response.json() == {
            "error": "rate_limiter_unavailable"
        }
        assert response.headers["retry-after"] == "1"
        assert client.get("/metrics").status_code == 200


def test_expired_finish_does_not_report_completion(database):  # noqa: F811
    sql = SqlBehaviorOutbox(database)
    with database.begin() as conn:
        event_id = sql.append(
            conn, InteractionActor(tenant_id="team", subject="one"), 1, "like", True
        )
    token, _ = sql.claim(event_id)
    with database.begin() as conn:
        conn.execute(
            outbox.update().values(lease_until=utcnow() - timedelta(seconds=1))
        )
    assert sql.finish(event_id, token, None, 5) is False
    assert sql.metrics_snapshot()["completed"] == 0


def test_epoch_gauge_keeps_timestamp_precision():
    epoch = 1791532000.123456
    text = RuntimeMetrics().render({"collected_unixtime": epoch})
    sample = next(
        line
        for line in text.splitlines()
        if line.startswith("safemeal_outbox_collected_unixtime ")
    )
    assert abs(float(sample.split()[1]) - epoch) < 0.001
