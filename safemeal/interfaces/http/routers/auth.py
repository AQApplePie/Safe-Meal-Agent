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
from safemeal.config.settings import settings
from safemeal.modules.identity.application import AuthService
from safemeal.interfaces.http.authentication import Principal, get_current_principal
from safemeal.interfaces.http.dependencies import get_auth_service


router = APIRouter()


def _require_local_identity() -> None:
    if settings.ENABLE_OIDC:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Local identity endpoints are disabled",
        )


@router.post("/register", response_model=AuthTokens, status_code=status.HTTP_201_CREATED)
def register(
    request: RegisterRequest,
    service: AuthService = Depends(get_auth_service),
) -> AuthTokens:
    _require_local_identity()
    return service.register(request)


@router.post("/login", response_model=AuthTokens)
def login(
    request: LoginRequest,
    service: AuthService = Depends(get_auth_service),
) -> AuthTokens:
    _require_local_identity()
    return service.login(request)


@router.post("/refresh", response_model=AuthTokens)
def refresh(
    request: RefreshRequest,
    service: AuthService = Depends(get_auth_service),
) -> AuthTokens:
    _require_local_identity()
    return service.refresh(request.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: LogoutRequest,
    service: AuthService = Depends(get_auth_service),
) -> Response:
    _require_local_identity()
    service.logout(request.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=CurrentIdentity)
def me(
    principal: Principal = Depends(get_current_principal),
    service: AuthService = Depends(get_auth_service),
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
