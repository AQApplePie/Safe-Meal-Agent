"""Hermetic defaults shared by SafeMeal's test suites."""

from __future__ import annotations

import os


os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ENABLE_LLM", "false")
os.environ.setdefault("ENABLE_EMBEDDINGS", "false")
os.environ.setdefault("ENABLE_MILVUS", "false")
os.environ.setdefault("ENABLE_NEO4J", "false")
os.environ.setdefault("ENABLE_OTEL", "false")
os.environ.setdefault("ENABLE_OIDC", "false")
os.environ.setdefault("ENABLE_AGENT_TRACE_PERSISTENCE", "false")
