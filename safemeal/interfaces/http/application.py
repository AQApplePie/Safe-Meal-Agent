"""两个 HTTP 入口共享的请求治理与异常契约。"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from safemeal.config.platform import PlatformSettings
from safemeal.interfaces.http import (
    RequestIdentityMiddleware,
    RedisTokenBucketMiddleware,
    RequestSizeLimitMiddleware,
)
from safemeal.shared.exceptions import (
    AccountDisabledError,
    AgentExecutionError,
    ApplicationError,
    AuthenticationError,
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


# 方法说明：configure_http
# 作用：注册应用的跨域、中间件与异常处理配置。
# 入参：
#   application（FastAPI）：当前 FastAPI 或 ASGI 应用。
#   settings（PlatformSettings）：当前入口的应用配置。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def configure_http(application: FastAPI, settings: PlatformSettings) -> None:
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
    application.add_middleware(RequestIdentityMiddleware)
    from safemeal.interfaces.http.metrics import configure_metrics

    configure_metrics(application, settings)

    # 方法说明：application_exception_handler
    # 作用：把已知应用异常转换为稳定 HTTP 错误响应。
    # 入参：
    #   request（Request）：HTTP 请求或应用层请求契约。
    #   exc（ApplicationError）：当前捕获或退出上下文时传入的异常对象。
    # 出参：JSONResponse；JSON HTTP 响应。
    @application.exception_handler(ApplicationError)
    async def application_exception_handler(
        request: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        if isinstance(exc, (ResourceOwnershipError, ResourceNotFoundError)):
            status_code = 404
        elif isinstance(exc, AccountDisabledError):
            status_code = 403
        elif isinstance(exc, AuthenticationError):
            status_code = 401
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

    # 方法说明：global_exception_handler
    # 作用：记录未预期异常并返回统一 HTTP 服务器错误。
    # 入参：
    #   request（Request）：HTTP 请求或应用层请求契约。
    #   exc（Exception）：当前捕获或退出上下文时传入的异常对象。
    # 出参：JSONResponse；JSON HTTP 响应。
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
