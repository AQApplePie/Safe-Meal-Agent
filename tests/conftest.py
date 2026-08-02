"""Hermetic defaults for tests that import process-scoped settings."""

from __future__ import annotations

import os


os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault(
    "DATABASE_URL",
    "mysql+aiomysql://safemeal:safemeal@127.0.0.1:3306/safemeal_test",
)
os.environ.setdefault(
    "MODEL_PRICING_JSON",
    '{"*":{"input_cost_per_million":2,"output_cost_per_million":10,'
    '"cached_input_cost_per_million":0.5}}',
)
