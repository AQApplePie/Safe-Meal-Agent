"""Composition facade for infrastructure operations used by HTTP entry points."""

from safemeal.infrastructure.operations.logging import configure_logging
from safemeal.infrastructure.operations.health import (
    get_runtime_readiness,
)
from safemeal.infrastructure.operations.rate_limit import RedisTokenBucket


def create_rate_limiter(url: str):
    return RedisTokenBucket(url, prefix="safemeal:http")


__all__ = [
    "configure_logging",
    "get_runtime_readiness",
    "create_rate_limiter",
]
