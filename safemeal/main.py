"""后端主应用入口。

当前项目采用“本地模块化单体”运行方式：Agent Orchestrator、Memory、
Tool 都在 ``safemeal`` 进程内完成调用，避免主链路被多服务 HTTP 调用打散。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from loguru import logger

from safemeal.bootstrap import ApplicationContainer
from safemeal.application.exceptions import (
    AgentExecutionError,
    ApplicationError,
    BusinessConstraintError,
    ConflictError,
    DatabaseOperationError,
    ExternalModelError,
    ExternalProviderError,
    ExternalServiceError,
    FeatureUnavailableError,
    InputValidationError,
    OperationTimeoutError,
    RateLimitExceededError,
    ResourceNotFoundError,
    ResourceOwnershipError,
)
from safemeal.config.settings import settings
from safemeal.infrastructure.operations.logging import configure_logging
from safemeal.infrastructure.operations.health import get_runtime_readiness
from safemeal.shared.types import JsonObject
from safemeal.interfaces.http import (
    RequestObservabilityMiddleware,
    RedisTokenBucketMiddleware,
    RequestSizeLimitMiddleware,
)
from safemeal.interfaces.mcp_server import create_authenticated_mcp_app
from safemeal.infrastructure.operations.telemetry import configure_telemetry


def _include_routers(application: FastAPI) -> None:
    """注册主后端全部 API 路由。

    这里不再区分 Orchestrator-only 模式。对于当前单 Agent 项目，``safemeal.main``
    就是完整后端入口：知识库、Agent 与 Memory 都在同一应用内暴露。
    """

    from safemeal.interfaces import api_router

    application.include_router(api_router, prefix=settings.API_V1_PREFIX)


@asynccontextmanager
async def lifespan(application: FastAPI):
    logger.info("Starting {} v{}", settings.APP_NAME, settings.APP_VERSION)
    logger.info("Debug mode: {}", settings.DEBUG)
    logger.info("API docs: http://{}:{}/docs", settings.HOST, settings.PORT)
    try:
        yield
    finally:
        await application.state.container.shutdown()
        logger.info("Shutting down {}", settings.APP_NAME)


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
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(
        RequestSizeLimitMiddleware,
        max_bytes=settings.HTTP_MAX_BODY_MB * 1024 * 1024,
    )
    if settings.REDIS_RATE_LIMIT_URL:
        application.add_middleware(
            RedisTokenBucketMiddleware,
            redis_url=settings.REDIS_RATE_LIMIT_URL,
            requests_per_minute=settings.HTTP_RATE_LIMIT_PER_MINUTE,
        )
    application.add_middleware(RequestObservabilityMiddleware)

    _include_routers(application)
    if settings.MCP_SERVER_ENABLED:
        application.mount(
            settings.MCP_SERVER_PATH,
            create_authenticated_mcp_app(application.state.container),
        )
    configure_telemetry(application, settings)

    @application.get("/")
    async def root_redirect():
        return RedirectResponse(url="/docs")

    @application.get("/favicon.ico")
    async def favicon():
        return Response(content=b"", media_type="image/x-icon")

    @application.get("/api")
    async def root() -> dict:
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "running",
            "docs": "/docs",
            "unavailable_routers": [],
        }

    @application.get("/health")
    async def health_check() -> dict:
        return {
            "status": "alive",
            "version": settings.APP_VERSION,
            "unavailable_routers": [],
        }

    @application.get("/livez", include_in_schema=False)
    async def liveness() -> dict:
        """Process liveness; deliberately performs no external network I/O."""

        return {"status": "alive"}

    @application.get("/readyz", include_in_schema=False)
    async def readiness() -> Response:
        """Configuration readiness without paid or destructive probes."""

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

    @application.exception_handler(ApplicationError)
    async def application_exception_handler(
        request: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        if isinstance(exc, (ResourceOwnershipError, ResourceNotFoundError)):
            status_code = 404
        elif isinstance(exc, ConflictError):
            status_code = 409
        elif isinstance(exc, (InputValidationError, BusinessConstraintError)):
            status_code = 422
        elif isinstance(exc, RateLimitExceededError):
            status_code = 429
        elif isinstance(exc, OperationTimeoutError):
            status_code = 504
        elif isinstance(exc, DatabaseOperationError):
            status_code = 503
        elif isinstance(exc, FeatureUnavailableError):
            status_code = 503
        elif isinstance(
            exc,
            (
                AgentExecutionError,
                ExternalModelError,
                ExternalServiceError,
                ExternalProviderError,
            ),
        ):
            status_code = 502
        else:
            status_code = 400
        logger.warning(
            "Application error on {} {} type={}",
            request.method,
            request.url.path,
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=status_code,
            content={"error": exc.code, "message": exc.public_message},
        )

    @application.exception_handler(Exception)
    async def global_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception("Unhandled exception on {} {}", request.method, request.url)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "message": (
                    str(exc) if settings.DEBUG else "An unexpected error occurred"
                ),
            },
        )

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
