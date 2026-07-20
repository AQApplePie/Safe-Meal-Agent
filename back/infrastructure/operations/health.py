"""外部依赖健康探测。

默认状态调用仅用于配置，不会执行网络 I/O 操作。

如果需要进行实际的连接性检查，请显式传递 ``probe=True`` 参数。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Awaitable, Callable, cast

import httpx

from SafeMealAgent.back.application.contracts.lightrag import SearchMode
from SafeMealAgent.back.config.settings import settings
from SafeMealAgent.back.shared.types import JsonObject


def _configured(value: object) -> bool:
    return value not in (None, "")


def _result(*, configured: bool, enabled: bool = True) -> JsonObject:
    if not enabled:
        return {"status": "disabled", "configured": configured}
    return {
        "status": "configured" if configured else "not_configured",
        "configured": configured,
    }


async def _probe_llm() -> JsonObject:
    from openai import AsyncOpenAI

    if not settings.LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY is not configured")
    client = AsyncOpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
    )
    try:
        await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[{"role": "user", "content": "Reply with OK."}],
            temperature=0,
            max_tokens=4,
        )
    finally:
        await client.close()
    return {"status": "ok", "configured": True, "model": settings.LLM_MODEL}


async def _probe_milvus() -> JsonObject:
    def check() -> list[str]:
        from pymilvus import connections, utility

        alias = "safemeal-health"
        connections.connect(
            alias=alias, host=settings.MILVUS_HOST, port=settings.MILVUS_PORT
        )
        try:
            return utility.list_collections(using=alias)
        finally:
            connections.disconnect(alias)

    collections = await asyncio.to_thread(check)
    return {"status": "ok", "configured": True, "collections": len(collections)}


async def _probe_neo4j() -> JsonObject:
    def check() -> None:
        from SafeMealAgent.back.infrastructure.retrieval.neo4j.client import create_driver

        driver = create_driver()
        try:
            driver.verify_connectivity()
        finally:
            driver.close()

    await asyncio.to_thread(check)
    return {"status": "ok", "configured": True, "database": settings.NEO4J_DATABASE}


async def _probe_lightrag() -> JsonObject:
    from SafeMealAgent.back.infrastructure.retrieval.lightrag.service import LightRAGService

    service = LightRAGService(
        working_dir=settings.LIGHTRAG_WORKING_DIR,
        default_mode=cast(SearchMode, settings.LIGHTRAG_RETRIEVAL_MODE),
        default_top_k=settings.LIGHTRAG_TOP_K,
    )
    try:
        await service.initialize()
        stats = service.get_index_stats()
        return {
            "status": "ok",
            "configured": True,
            "initialized": stats["initialized"],
            "total_size_mb": stats["total_size_mb"],
        }
    finally:
        await service.cleanup()


async def _probe_database() -> JsonObject:
    def check() -> None:
        from sqlalchemy import inspect, text

        from SafeMealAgent.back.infrastructure.persistence.database import get_engine

        engine = get_engine()
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        required_tables = {
            "chat_sessions",
            "chat_messages",
            "user_memories",
        }
        missing = required_tables - set(inspect(engine).get_table_names())
        if missing:
            raise RuntimeError(f"database migrations missing tables: {sorted(missing)}")

    await asyncio.to_thread(check)
    return {"status": "ok", "configured": True}


async def _probe_tika() -> JsonObject:
    async with httpx.AsyncClient(timeout=settings.INTEGRATION_PROBE_TIMEOUT) as client:
        response = await client.get(f"{settings.TIKA_URL.rstrip('/')}/version")
        response.raise_for_status()
    return {
        "status": "ok",
        "configured": True,
        "version": response.text.strip(),
    }


async def _safe_probe(probe: Callable[[], Awaitable[JsonObject]]) -> JsonObject:
    try:
        return await asyncio.wait_for(
            probe(), timeout=settings.INTEGRATION_PROBE_TIMEOUT
        )
    except Exception as exc:
        return {
            "status": "error",
            "configured": True,
            "error": type(exc).__name__,
            "detail": str(exc) if settings.DEBUG else "Connectivity probe failed",
        }


async def get_integration_status(*, probe: bool = False) -> JsonObject:
    llm_configured = _configured(settings.LLM_API_KEY)
    embedding_configured = _configured(
        settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
    )
    lightrag_configured = (
        llm_configured
        and embedding_configured
        and Path(settings.LIGHTRAG_WORKING_DIR).exists()
    )
    statuses: dict[str, JsonObject] = {
        "llm": _result(configured=llm_configured, enabled=settings.ENABLE_LLM),
        "milvus": _result(configured=True, enabled=settings.ENABLE_MILVUS),
        "neo4j": _result(
            configured=_configured(settings.NEO4J_URI),
            enabled=settings.ENABLE_NEO4J,
        ),
        "lightrag": _result(
            configured=lightrag_configured,
            enabled=settings.ENABLE_LIGHTRAG,
        ),
        "tika": _result(configured=True, enabled=settings.TIKA_ENABLED),
    }
    statuses["embedding"] = _result(
        configured=embedding_configured,
        enabled=settings.ENABLE_EMBEDDINGS,
    )

    if probe:
        probes = {
            "llm": (settings.ENABLE_LLM and llm_configured, _probe_llm),
            "milvus": (settings.ENABLE_MILVUS, _probe_milvus),
            "neo4j": (
                settings.ENABLE_NEO4J and _configured(settings.NEO4J_URI),
                _probe_neo4j,
            ),
            "lightrag": (
                settings.ENABLE_LIGHTRAG and lightrag_configured,
                _probe_lightrag,
            ),
            "tika": (settings.TIKA_ENABLED, _probe_tika),
        }
        for name, (should_probe, probe_func) in probes.items():
            if should_probe:
                statuses[name] = await _safe_probe(probe_func)

    overall = "ok"
    if any(item["status"] == "error" for item in statuses.values()):
        overall = "degraded"
    return {"status": overall, "probe": probe, "integrations": statuses}


async def get_runtime_readiness() -> JsonObject:
    """Probe required, non-billable runtime dependencies for orchestration readiness."""

    checks: dict[str, JsonObject] = {
        "database": await _safe_probe(_probe_database),
    }
    probes: list[tuple[str, Callable[[], Awaitable[JsonObject]]]] = []
    if settings.ENABLE_MILVUS:
        probes.append(("milvus", _probe_milvus))
    if settings.ENABLE_NEO4J:
        probes.append(("neo4j", _probe_neo4j))
    if settings.TIKA_ENABLED:
        probes.append(("tika", _probe_tika))
    if probes:
        results = await asyncio.gather(
            *(_safe_probe(probe) for _, probe in probes),
        )
        checks.update({name: result for (name, _), result in zip(probes, results)})
    status = (
        "ready"
        if all(item.get("status") == "ok" for item in checks.values())
        else "not_ready"
    )
    return {"status": status, "checks": checks}
