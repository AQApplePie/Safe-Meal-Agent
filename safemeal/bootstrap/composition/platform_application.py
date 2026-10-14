"""独立后端应用工厂与存储就绪探测。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from redis import Redis, ConnectionPool
from sqlalchemy import inspect, text
from safemeal.config.platform import PlatformSettings
from safemeal.bootstrap.composition.platform_container import PlatformContainer
from safemeal.bootstrap.composition.operations import configure_logging
from safemeal.infrastructure.persistence.database import get_engine
from safemeal.interfaces import build_api_router
from safemeal.interfaces.http.application import configure_http

_REQUIRED_TABLES = {
    "recipes",
    "ingredients",
    "recipe_ingredients",
    "recipe_steps",
    "cuisines",
    "users",
    "refresh_tokens",
    "recipe_reactions",
    "recipe_view_history",
    "behavior_outbox",
}


# 方法说明：_storage_readiness
# 作用：探测持久化与外部检索存储的就绪状态。
# 入参：
#   config（PlatformSettings）：图调用或检查点配置。
# 出参：dict；平台存储依赖的就绪状态与检查详情。
def _storage_readiness(config: PlatformSettings) -> dict:
    checks = {}
    try:
        engine = get_engine()
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        missing = _REQUIRED_TABLES - set(inspect(engine).get_table_names())
        checks["database"] = (
            {"status": "error", "missing_tables": sorted(missing)}
            if missing
            else {"status": "ok"}
        )
    except Exception as exc:
        checks["database"] = {"status": "error", "error": type(exc).__name__}
    urls = {
        "rate_limit": config.REDIS_RATE_LIMIT_URL,
        "recipe_cache": config.RECIPE_CACHE_URL,
        "ranking": config.RECIPE_RANKING_REDIS_URL,
        "behavior_events": config.BEHAVIOR_EVENT_REDIS_URL,
    }
    for name, url in urls.items():
        if not url:
            continue
        try:
            pool = ConnectionPool.from_url(
                url, socket_connect_timeout=0.2, socket_timeout=0.2
            )
            client = Redis(connection_pool=pool)
            try:
                client.ping()
            finally:
                client.close()
                pool.disconnect()
            checks[name] = {"status": "ok"}
        except Exception as exc:
            checks[name] = {"status": "error", "error": type(exc).__name__}
    return {
        "status": "ready"
        if all(c["status"] == "ok" for c in checks.values())
        else "not_ready",
        "checks": checks,
    }


# 方法说明：create_platform_application
# 作用：装配不依赖 Agent 运行时的平台 FastAPI 应用。
# 入参：
#   config（PlatformSettings | None）：图调用或检查点配置；默认值为 None。
# 出参：FastAPI；FastAPI 应用。
def create_platform_application(config: PlatformSettings | None = None) -> FastAPI:
    config = config if config is not None else PlatformSettings()  # type: ignore[call-arg]
    configure_logging(debug=config.DEBUG)

    # 方法说明：lifespan
    # 作用：管理应用启动与关闭，装配资源并回收后台任务与连接。
    # 入参：
    #   application（FastAPI）：当前 FastAPI 或 ASGI 应用。
    # 出参：按实现返回；异步生命周期上下文；进入时启动后台任务，退出时关闭资源。
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            application.state.container.start_ranking_worker()
            yield
        finally:
            await application.state.container.shutdown()

    application = FastAPI(
        title=config.APP_NAME, version=config.APP_VERSION, lifespan=lifespan
    )
    application.state.settings = config
    application.state.container = PlatformContainer(config)
    configure_http(application, config)
    application.include_router(
        build_api_router(include_agent=False), prefix=config.API_V1_PREFIX
    )

    # 方法说明：root
    # 作用：响应根路径或将请求引导至接口文档入口。
    # 入参：
    #   无显式入参。
    # 出参：RedirectResponse；指向平台接口文档的重定向响应。
    @application.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse("/docs")

    # 方法说明：info
    # 作用：返回平台名称、入口与能力范围等服务信息。
    # 入参：
    #   无显式入参。
    # 出参：dict；平台名称与服务状态信息。
    @application.get("/api")
    async def info():
        return {
            "name": config.APP_NAME,
            "version": config.APP_VERSION,
            "runtime": "platform",
            "docs": "/docs",
        }

    # 方法说明：live
    # 作用：报告当前服务进程是否仍能响应请求。
    # 入参：
    #   无显式入参。
    # 出参：dict；服务进程的存活状态。
    @application.get("/health")
    @application.get("/livez", include_in_schema=False)
    async def live():
        return {"status": "alive", "version": config.APP_VERSION}

    # 方法说明：ready
    # 作用：报告核心依赖是否满足提供服务的条件。
    # 入参：
    #   无显式入参。
    # 出参：JSONResponse；核心依赖就绪时返回成功，否则返回不可用状态。
    @application.get("/readyz", include_in_schema=False)
    async def ready():
        payload = await asyncio.to_thread(_storage_readiness, config)
        return JSONResponse(
            status_code=200 if payload["status"] == "ready" else 503, content=payload
        )

    return application
