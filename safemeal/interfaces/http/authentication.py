"""Small single-host API-key authentication boundary."""

from __future__ import annotations

from dataclasses import dataclass
from hmac import compare_digest
from fastapi import Header, HTTPException, status
import jwt

from safemeal.config.settings import settings


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
    api_key: str | None = Header(default=None, alias="X-API-Key"),
    subject: str | None = Header(default=None, alias="X-SafeMeal-User-ID"),
    tenant_id: str | None = Header(default=None, alias="X-SafeMeal-Tenant-ID"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> Principal:
    """Require one optional local API key and accept a demo user header."""

    return authenticate_credentials(
        api_key=api_key,
        subject=subject,
        tenant_id=tenant_id,
        authorization=authorization,
    )


def authenticate_credentials(
    *,
    api_key: str | None,
    subject: str | None,
    tenant_id: str | None,
    authorization: str | None,
) -> Principal:
    """Authenticate HTTP or mounted-ASGI requests through one boundary."""

    if settings.ENABLE_OIDC:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.casefold() != "bearer" or not token:
            raise HTTPException(status_code=401, detail="Bearer token is required")
        return _oidc_principal(token)

    expected_key = (settings.API_KEY or "").strip()
    if expected_key and (not api_key or not compare_digest(api_key, expected_key)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
        )
    return Principal(
        subject=(subject or "demo-user").strip() or "demo-user",
        tenant_id=(tenant_id or settings.DEFAULT_TENANT_ID).strip()
        or settings.DEFAULT_TENANT_ID,
    )


def authorize_user_id(principal: Principal, claimed_user_id: str) -> str:
    """Bind a user-owned resource to the authenticated principal."""

    claimed = claimed_user_id.strip() or principal.subject
    if claimed not in {principal.subject, principal.storage_subject}:
        raise HTTPException(status_code=403, detail="Cannot access another user")
    return principal.storage_subject


__all__ = [
    "Principal",
    "authenticate_credentials",
    "authorize_user_id",
    "get_current_principal",
]
