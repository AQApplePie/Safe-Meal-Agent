"""实现 HTTP 接口层的请求与响应适配。"""

from fastapi import APIRouter, Depends, HTTPException, Response, status

from safemeal.modules.identity.contracts import (
    AuthTokens,
    CurrentIdentity,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
)
from safemeal.config.platform import PlatformSettings
from safemeal.modules.identity.application import AuthService
from safemeal.interfaces.http.authentication import Principal, get_current_principal
from safemeal.interfaces.http.platform_dependencies import (
    get_auth_service,
    get_http_settings,
)


router = APIRouter()


# 方法说明：_require_local_identity
# 作用：确认当前令牌属于受支持的本地身份体系。
# 入参：
#   settings（PlatformSettings）：当前入口的应用配置。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
def _require_local_identity(settings: PlatformSettings) -> None:
    if settings.ENABLE_OIDC:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Local identity endpoints are disabled",
        )


# 方法说明：register
# 作用：创建租户内用户并签发首次登录令牌。
# 入参：
#   request（RegisterRequest）：用户注册请求。
#   service（AuthService）：注册登录与令牌管理服务；由 FastAPI 依赖注入。
#   settings（PlatformSettings）：当前入口的应用配置；由 FastAPI 依赖注入。
# 出参：AuthTokens；访问与刷新令牌响应。
@router.post(
    "/register", response_model=AuthTokens, status_code=status.HTTP_201_CREATED
)
def register(
    request: RegisterRequest,
    service: AuthService = Depends(get_auth_service),
    settings: PlatformSettings = Depends(get_http_settings),
) -> AuthTokens:
    _require_local_identity(settings)
    return service.register(request)


# 方法说明：login
# 作用：校验租户、账号与密码并签发登录令牌。
# 入参：
#   request（LoginRequest）：用户登录请求。
#   service（AuthService）：注册登录与令牌管理服务；由 FastAPI 依赖注入。
#   settings（PlatformSettings）：当前入口的应用配置；由 FastAPI 依赖注入。
# 出参：AuthTokens；访问与刷新令牌响应。
@router.post("/login", response_model=AuthTokens)
def login(
    request: LoginRequest,
    service: AuthService = Depends(get_auth_service),
    settings: PlatformSettings = Depends(get_http_settings),
) -> AuthTokens:
    _require_local_identity(settings)
    return service.login(request)


# 方法说明：refresh
# 作用：校验并轮换刷新令牌，重新签发访问令牌。
# 入参：
#   request（RefreshRequest）：刷新登录令牌请求。
#   service（AuthService）：注册登录与令牌管理服务；由 FastAPI 依赖注入。
#   settings（PlatformSettings）：当前入口的应用配置；由 FastAPI 依赖注入。
# 出参：AuthTokens；访问与刷新令牌响应。
@router.post("/refresh", response_model=AuthTokens)
def refresh(
    request: RefreshRequest,
    service: AuthService = Depends(get_auth_service),
    settings: PlatformSettings = Depends(get_http_settings),
) -> AuthTokens:
    _require_local_identity(settings)
    return service.refresh(request.refresh_token)


# 方法说明：logout
# 作用：撤销当前刷新令牌或用户已有登录凭据。
# 入参：
#   request（LogoutRequest）：用户登出请求。
#   service（AuthService）：注册登录与令牌管理服务；由 FastAPI 依赖注入。
#   settings（PlatformSettings）：当前入口的应用配置；由 FastAPI 依赖注入。
# 出参：Response；HTTP 响应。
@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: LogoutRequest,
    service: AuthService = Depends(get_auth_service),
    settings: PlatformSettings = Depends(get_http_settings),
) -> Response:
    _require_local_identity(settings)
    service.logout(request.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# 方法说明：me
# 作用：读取当前已认证用户的身份信息。
# 入参：
#   principal（Principal）：通过认证后建立的可信身份主体；由 FastAPI 依赖注入。
#   service（AuthService）：注册登录与令牌管理服务；由 FastAPI 依赖注入。
#   settings（PlatformSettings）：当前入口的应用配置；由 FastAPI 依赖注入。
# 出参：CurrentIdentity；当前用户身份响应。
@router.get("/me", response_model=CurrentIdentity)
def me(
    principal: Principal = Depends(get_current_principal),
    service: AuthService = Depends(get_auth_service),
    settings: PlatformSettings = Depends(get_http_settings),
) -> CurrentIdentity:
    if settings.ENABLE_OIDC:
        return CurrentIdentity(
            subject=principal.subject,
            tenant_id=principal.tenant_id,
            roles=principal.roles,
            provider="oidc",
        )
    user = service.get_user(principal.subject)
    return CurrentIdentity(
        subject=user.id,
        tenant_id=user.tenant_id,
        roles=user.roles,
        provider="local",
        email=user.email,
        display_name=user.display_name,
        status=user.status,
    )


__all__ = ["router"]
