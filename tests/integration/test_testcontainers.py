from __future__ import annotations

import os

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.testcontainers]


@pytest.mark.skipif(
    os.getenv("RUN_TESTCONTAINERS") != "1",
    reason="set RUN_TESTCONTAINERS=1 to start disposable infrastructure",
)
def test_mysql_and_redis_are_real_services() -> None:
    pytest.importorskip("testcontainers")
    from redis import Redis
    from sqlalchemy import create_engine, text
    from testcontainers.mysql import MySqlContainer
    from testcontainers.redis import RedisContainer

    with (
        MySqlContainer("mysql:8.0") as mysql,
        RedisContainer("redis:7-alpine") as redis,
    ):
        engine = create_engine(mysql.get_connection_url())
        with engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar_one() == 1
        client = Redis.from_url(redis.get_connection_url())
        assert client.ping() is True
