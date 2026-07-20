"""Trusted-gateway authentication and role authorization for HTTP routes."""

from __future__ import annotations

from dataclasses import dataclass
from hmac import compare_digest
from typing import FrozenSet

from fastapi import Depends, Header, HTTPException, status

from SafeMealAgent.back.config.settings import settings


_KNOWN_ROLES = frozenset({"user", "admin", "internal"})


@dataclass(frozen=True)
class Principal:
    """Identity asserted by the configured trusted gateway."""

    subject: str
    roles: FrozenSet[str]
    trusted: bool


def get_current_principal(
    gateway_secret: str | None = Header(
        default=None, alias="X-SafeMeal-Gateway-Secret"
    ),
    subject: str | None = Header(default=None, alias="X-SafeMeal-User-ID"),
    role_header: str | None = Header(default=None, alias="X-SafeMeal-Roles"),
) -> Principal:
    """Authenticate an identity asserted by the trusted gateway."""

    normalized_subject = (subject or "").strip()
    if settings.AUTH_MODE == "disabled":
        return Principal(
            subject=normalized_subject or "development-user",
            roles=_KNOWN_ROLES,
            trusted=False,
        )

    expected_secret = settings.AUTH_GATEWAY_SECRET or ""
    if not gateway_secret or not compare_digest(gateway_secret, expected_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid trusted gateway credentials",
        )
    if not normalized_subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Trusted gateway did not provide a user identity",
        )

    requested_roles = {
        role.strip().casefold()
        for role in (role_header or "user").split(",")
        if role.strip()
    }
    roles = frozenset(requested_roles & _KNOWN_ROLES)
    if not roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal has no recognized role",
        )
    return Principal(subject=normalized_subject, roles=roles, trusted=True)


def require_authenticated(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    return principal


def _require_role(principal: Principal, role: str) -> Principal:
    if role not in principal.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"The {role} role is required",
        )
    return principal


def require_admin(principal: Principal = Depends(get_current_principal)) -> Principal:
    return _require_role(principal, "admin")


def require_internal(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    return _require_role(principal, "internal")


def authorize_user_id(principal: Principal, claimed_user_id: str) -> str:
    """Bind a user-owned resource to the authenticated principal."""

    normalized = claimed_user_id.strip()
    if principal.trusted and normalized != principal.subject:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The requested user does not match the authenticated principal",
        )
    return principal.subject if principal.trusted else normalized


__all__ = [
    "Principal",
    "authorize_user_id",
    "get_current_principal",
    "require_admin",
    "require_authenticated",
    "require_internal",
]
