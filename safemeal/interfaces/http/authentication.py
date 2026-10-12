"""实现 HTTP 接口层的请求与响应适配。"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
import json
import re
from pydantic import ValidationError
from safemeal.modules.interaction.contracts.models import InteractionActor
from fastapi import Depends, Header, HTTPException
import jwt

from safemeal.config.platform import PlatformSettings
from safemeal.modules.identity.application import AuthService
from safemeal.interfaces.http.platform_dependencies import (
    get_auth_service,
    get_http_settings,
)


# 类说明（数据契约类）：Principal
# 作用：描述认证后的可信身份主体的结构、类型及可校验字段。
@dataclass(frozen=True)
class Principal:
    # 字段说明：subject
    # 作用：当前身份的用户主体标识。
    # 类型：str。
    subject: str
    # 字段说明：tenant_id
    # 作用：可信租户标识，用于业务数据隔离。
    # 类型：str。
    # 初始值：'default'。
    tenant_id: str = "default"
    # 字段说明：roles
    # 作用：用户拥有的角色集合。
    # 类型：tuple[str, ...]。
    # 初始值：()。
    roles: tuple[str, ...] = ()

    # 方法说明：storage_subject
    # 作用：生成含租户边界的持久化用户标识。
    # 入参：
    #   无显式入参。
    # 出参：str；用于持久化隔离的租户与用户组合标识。
    @property
    def storage_subject(self) -> str:

        legacy = f"{self.tenant_id}:{self.subject}"
        # Preserve ordinary local account keys. Encode delimiter/case/Unicode
        # identities to avoid aliases and fit the existing 255-character columns.
        if len(legacy) <= 255 and all(
            re.fullmatch(r"[a-z0-9_-]+", item)
            for item in (self.tenant_id, self.subject)
        ):
            return legacy
        payload = json.dumps(
            [self.tenant_id, self.subject], ensure_ascii=True, separators=(",", ":")
        )
        # No colon: encoded keys cannot overlap any legacy tenant:subject key.
        return "principal_" + sha256(payload.encode()).hexdigest()


# 方法说明：_jwks_client
# 作用：创建并缓存 OIDC 公钥获取客户端。
# 入参：
#   url（str）：当前外部资源或服务的连接地址。
# 出参：jwt.PyJWKClient；jwt.PyJWKClient。
@lru_cache(maxsize=8)
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_jwk_set=True, lifespan=300)


# 方法说明：_oidc_principal
# 作用：校验 OIDC 令牌并转换为可信身份主体。
# 入参：
#   token（str）：令牌或本次租约的处理凭证。
#   settings（PlatformSettings）：当前入口的应用配置。
# 出参：Principal；认证后的可信身份主体。
def _oidc_principal(token: str, settings: PlatformSettings) -> Principal:
    if not settings.OIDC_ISSUER or not settings.OIDC_AUDIENCE:
        raise HTTPException(status_code=503, detail="OIDC is not fully configured")
    jwks_url = settings.OIDC_JWKS_URL or (
        settings.OIDC_ISSUER.rstrip("/") + "/.well-known/jwks.json"
    )
    try:
        signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=[item.strip() for item in settings.OIDC_ALGORITHMS.split(",")],
            audience=settings.OIDC_AUDIENCE,
            issuer=settings.OIDC_ISSUER,
            options={"require": ["exp", "iat", "sub"]},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=401, detail="Invalid OIDC access token"
        ) from exc
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise HTTPException(status_code=401, detail="Invalid OIDC subject")
    tenant = claims.get(settings.OIDC_TENANT_CLAIM)
    if not isinstance(tenant, str) or not tenant.strip():
        raise HTTPException(status_code=403, detail="OIDC token has no tenant claim")
    raw_roles = claims.get("roles", [])
    roles = (
        tuple(str(item) for item in raw_roles) if isinstance(raw_roles, list) else ()
    )
    return Principal(subject=subject, tenant_id=tenant, roles=roles)


# 方法说明：get_current_principal
# 作用：从请求令牌建立并返回可信身份主体。
# 入参：
#   authorization（str | None）：HTTP Authorization 请求头；默认值为 Header(default=None,
# alias='Authorization')。
#   auth_service（AuthService）：身份认证与令牌业务服务；由 FastAPI 依赖注入。
#   settings（PlatformSettings）：当前入口的应用配置；由 FastAPI 依赖注入。
# 出参：Principal；认证后的可信身份主体。
def get_current_principal(
    authorization: str | None = Header(default=None, alias="Authorization"),
    auth_service: AuthService = Depends(get_auth_service),
    settings: PlatformSettings = Depends(get_http_settings),
) -> Principal:

    if settings.ENABLE_OIDC:
        return _oidc_principal(_bearer_token(authorization), settings)
    user = auth_service.authenticate_access_token(_bearer_token(authorization))
    return Principal(
        subject=user.id,
        tenant_id=user.tenant_id,
        roles=tuple(user.roles),
    )


# 方法说明：_bearer_token
# 作用：从 Authorization 头提取 Bearer 令牌并校验格式。
# 入参：
#   authorization（str | None）：HTTP Authorization 请求头。
# 出参：str；去除 Bearer 前缀后的原始访问令牌。
def _bearer_token(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.casefold() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Bearer token is required")
    return token.strip()


# 方法说明：get_interaction_actor
# 作用：把认证身份转换为行为模块使用的租户与用户主体。
# 入参：
#   principal（Principal）：通过认证后建立的可信身份主体；由 FastAPI 依赖注入。
# 出参：InteractionActor；行为操作租户与用户主体。
def get_interaction_actor(
    principal: Principal = Depends(get_current_principal),
) -> InteractionActor:
    try:
        return InteractionActor(
            tenant_id=principal.tenant_id, subject=principal.subject
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=403, detail="Unsupported interaction identity"
        ) from exc


__all__ = [
    "Principal",
    "get_current_principal",
    "get_interaction_actor",
]
