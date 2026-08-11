"""Small single-host API-key authentication boundary."""

from __future__ import annotations

from dataclasses import dataclass
from hmac import compare_digest
from fastapi import Header, HTTPException, status

from safemeal.config.settings import settings


@dataclass(frozen=True)
class Principal:
    """Caller identity used to scope sessions and memories."""

    subject: str


def get_current_principal(
    api_key: str | None = Header(default=None, alias="X-API-Key"),
    subject: str | None = Header(default=None, alias="X-SafeMeal-User-ID"),
) -> Principal:
    """Require one optional local API key and accept a demo user header."""

    expected_key = (settings.API_KEY or "").strip()
    if expected_key and (not api_key or not compare_digest(api_key, expected_key)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
        )
    return Principal(subject=(subject or "demo-user").strip() or "demo-user")


def authorize_user_id(principal: Principal, claimed_user_id: str) -> str:
    """Bind a user-owned resource to the authenticated principal."""

    return claimed_user_id.strip() or principal.subject


__all__ = [
    "Principal",
    "authorize_user_id",
    "get_current_principal",
]
