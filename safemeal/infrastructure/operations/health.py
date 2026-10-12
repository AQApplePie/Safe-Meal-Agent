"""外部依赖健康探测。

默认状态调用仅用于配置，不会执行网络 I/O 操作。

如果需要进行实际的连接性检查，请显式传递 ``probe=True`` 参数。
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from safemeal.config.settings import settings
from safemeal.shared.types import JsonObject


# 方法说明：_probe_milvus
# 作用：探测 Milvus 服务及目标集合的可用状态。
# 入参：
#   无显式入参。
# 出参：JsonObject；JSON 字段映射。
async def _probe_milvus() -> JsonObject:
    # 方法说明：check
    # 作用：探测当前外部存储连接，并按依赖类型检查可用集合或必要表结构。
    # 入参：
    #   无显式入参。
    # 出参：list[str]；文本字符串的集合。
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


# 方法说明：_probe_neo4j
# 作用：探测 Neo4j 驱动连接及数据库可用状态。
# 入参：
#   无显式入参。
# 出参：JsonObject；JSON 字段映射。
async def _probe_neo4j() -> JsonObject:
    # 方法说明：check
    # 作用：探测当前外部存储连接，并按依赖类型检查可用集合或必要表结构。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def check() -> None:
        from safemeal.infrastructure.retrieval.neo4j.recipe_graph import create_driver

        driver = create_driver()
        try:
            driver.verify_connectivity()
        finally:
            driver.close()

    await asyncio.to_thread(check)
    return {"status": "ok", "configured": True, "database": settings.NEO4J_DATABASE}


# 方法说明：_probe_database
# 作用：探测 SQL 数据库是否可建立连接并执行查询。
# 入参：
#   无显式入参。
# 出参：JsonObject；JSON 字段映射。
async def _probe_database() -> JsonObject:
    # 方法说明：check
    # 作用：探测当前外部存储连接，并按依赖类型检查可用集合或必要表结构。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def check() -> None:
        from sqlalchemy import inspect, text

        from safemeal.infrastructure.persistence.database import get_engine

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


# 方法说明：_safe_probe
# 作用：为外部依赖探测应用超时和异常隔离，返回就绪状态。
# 入参：
#   probe（Callable[[], Awaitable[JsonObject]]）：外部依赖探测函数。
# 出参：JsonObject；JSON 字段映射。
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


# 方法说明：get_runtime_readiness
# 作用：综合数据库和检索依赖的探测结果，生成运行就绪状态。
# 入参：
#   无显式入参。
# 出参：JsonObject；JSON 字段映射。
async def get_runtime_readiness() -> JsonObject:

    checks: dict[str, JsonObject] = {
        "database": await _safe_probe(_probe_database),
    }
    probes: list[tuple[str, Callable[[], Awaitable[JsonObject]]]] = []
    if settings.ENABLE_MILVUS:
        probes.append(("retrieval", _probe_milvus))
    if settings.ENABLE_NEO4J:
        probes.append(("neo4j", _probe_neo4j))
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
