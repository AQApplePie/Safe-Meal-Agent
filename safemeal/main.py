"""后端主应用入口。

当前项目采用“本地模块化单体”运行方式：Agent Orchestrator、Memory、
Tool 都在 ``safemeal`` 进程内完成调用，避免主链路被多服务 HTTP 调用打散。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse, Response
from loguru import logger

from safemeal.bootstrap.composition.application_container import (
    ApplicationContainer,
)
from safemeal.config.settings import settings
from safemeal.interfaces.http.application import configure_http
from safemeal.bootstrap.composition.operations import configure_logging
from safemeal.bootstrap.composition.operations import get_runtime_readiness
from safemeal.shared.types import JsonObject


# 方法说明：_include_routers
# 作用：注册主后端全部 API 路由。
# 入参：
#   application（FastAPI）：当前 FastAPI 或 ASGI 应用。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def _include_routers(application: FastAPI) -> None:
    """注册主后端全部 API 路由。

    这里不再区分 Orchestrator-only 模式。对于当前单 Agent 项目，``safemeal.main``
    就是完整后端入口：知识库、Agent 与 Memory 都在同一应用内暴露。
    """

    from safemeal.interfaces import api_router

    application.include_router(api_router, prefix=settings.API_V1_PREFIX)


# 方法说明：lifespan
# 作用：管理应用启动与关闭，装配资源并回收后台任务与连接。
# 入参：
#   application（FastAPI）：当前 FastAPI 或 ASGI 应用。
# 出参：按实现返回；异步生命周期上下文；进入时启动后台任务，退出时关闭资源。
@asynccontextmanager
async def lifespan(application: FastAPI):
    logger.info("Starting {} v{}", settings.APP_NAME, settings.APP_VERSION)
    logger.info("Debug mode: {}", settings.DEBUG)
    logger.info("API docs: http://{}:{}/docs", settings.HOST, settings.PORT)
    try:
        application.state.container.start_ranking_worker()
        yield
    finally:
        await application.state.container.shutdown()
        logger.info("Shutting down {}", settings.APP_NAME)


# 方法说明：create_application
# 作用：装配完整 Agent 后端的 FastAPI 应用。
# 入参：
#   无显式入参。
# 出参：FastAPI；FastAPI 应用。
def create_application() -> FastAPI:
    configure_logging(debug=settings.DEBUG)
    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Single-agent culinary assistant with typed recipe tools",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    application.state.container = ApplicationContainer()
    application.state.settings = settings
    configure_http(application, settings)

    _include_routers(application)

    # 方法说明：root_redirect
    # 作用：响应根路径或将请求引导至接口文档入口。
    # 入参：
    #   无显式入参。
    # 出参：RedirectResponse；指向接口文档的重定向响应。
    @application.get("/")
    async def root_redirect():
        return RedirectResponse(url="/docs")

    # 方法说明：favicon
    # 作用：响应浏览器站点图标请求。
    # 入参：
    #   无显式入参。
    # 出参：Response；无需正文的站点图标响应。
    @application.get("/favicon.ico")
    async def favicon():
        return Response(content=b"", media_type="image/x-icon")

    # 方法说明：root
    # 作用：响应根路径或将请求引导至接口文档入口。
    # 入参：
    #   无显式入参。
    # 出参：dict；结构化字段映射。
    @application.get("/api")
    async def root() -> dict:
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "running",
            "docs": "/docs",
            "unavailable_routers": [],
        }

    # 方法说明：health_check
    # 作用：报告当前服务进程是否仍能响应请求。
    # 入参：
    #   无显式入参。
    # 出参：dict；结构化字段映射。
    @application.get("/health")
    async def health_check() -> dict:
        return {
            "status": "alive",
            "version": settings.APP_VERSION,
            "unavailable_routers": [],
        }

    # 方法说明：liveness
    # 作用：报告当前服务进程是否仍能响应请求。
    # 入参：
    #   无显式入参。
    # 出参：dict；结构化字段映射。
    @application.get("/livez", include_in_schema=False)
    async def liveness() -> dict:

        return {"status": "alive"}

    # 方法说明：readiness
    # 作用：报告核心依赖是否满足提供服务的条件。
    # 入参：
    #   无显式入参。
    # 出参：Response；HTTP 响应。
    @application.get("/readyz", include_in_schema=False)
    async def readiness() -> Response:

        issues = settings.configuration_issues
        runtime: JsonObject = (
            {"status": "not_checked", "checks": {}}
            if issues
            else await get_runtime_readiness()
        )
        ready = not issues and runtime.get("status") == "ready"
        payload = {
            "status": "ready" if ready else "not_ready",
            "enabled": {
                "llm": settings.ENABLE_LLM,
                "embeddings": settings.ENABLE_EMBEDDINGS,
                "retrieval": settings.ENABLE_MILVUS,
                "neo4j": settings.ENABLE_NEO4J,
            },
            "issues": issues,
            "runtime": runtime,
        }
        return JSONResponse(status_code=200 if ready else 503, content=payload)

    return application


application = create_application()
app = application


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "safemeal.main:application",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info",
    )
