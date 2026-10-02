"""Human bearer-token authentication boundary."""

from __future__ import annotations

from dataclasses import dataclass
from fastapi import Depends, Header, HTTPException
import jwt

from safemeal.config.settings import settings
from safemeal.application.service.auth import AuthService
from safemeal.interfaces.http.dependencies import get_auth_service


@dataclass(frozen=True)
class Principal:
    """Caller identity used to scope sessions and memories."""

    subject: str
    tenant_id: str = "default"
    roles: tuple[str, ...] = ()

    @property
    def storage_subject(self) -> str:
        """Collision-free identity used by existing persistence ports."""

        return f"{self.tenant_id}:{self.subject}"


def _oidc_principal(token: str) -> Principal:
    if not settings.OIDC_ISSUER or not settings.OIDC_AUDIENCE:
        raise HTTPException(status_code=503, detail="OIDC is not fully configured")
    jwks_url = settings.OIDC_JWKS_URL or (
        settings.OIDC_ISSUER.rstrip("/") + "/.well-known/jwks.json"
    )
    try:
        signing_key = jwt.PyJWKClient(
            jwks_url, cache_jwk_set=True
        ).get_signing_key_from_jwt(token)
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
    tenant = str(claims.get(settings.OIDC_TENANT_CLAIM) or "").strip()
    if not tenant:
        raise HTTPException(status_code=403, detail="OIDC token has no tenant claim")
    raw_roles = claims.get("roles", [])
    roles = (
        tuple(str(item) for item in raw_roles) if isinstance(raw_roles, list) else ()
    )
    return Principal(subject=str(claims["sub"]), tenant_id=tenant, roles=roles)


def get_current_principal(
    authorization: str | None = Header(default=None, alias="Authorization"),
    auth_service: AuthService = Depends(get_auth_service),
) -> Principal:
    """Authenticate a human API request from a signed access token."""

    if settings.ENABLE_OIDC:
        return _oidc_principal(_bearer_token(authorization))
    user = auth_service.authenticate_access_token(_bearer_token(authorization))
    return Principal(
        subject=user.id,
        tenant_id=user.tenant_id,
        roles=tuple(user.roles),
    )


def _bearer_token(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.casefold() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Bearer token is required")
    return token.strip()


__all__ = [
    "Principal",
    "get_current_principal",
]
