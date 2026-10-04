"""Password and access-token boundaries implemented by infrastructure adapters."""

from datetime import datetime
from typing import Protocol

from safemeal.application.contracts.auth import AccessTokenClaims


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...
    def verify(self, password_hash: str, password: str) -> bool: ...
    def needs_rehash(self, password_hash: str) -> bool: ...


class TokenIssuer(Protocol):
    def issue_access_token(
        self,
        *,
        subject: str,
        tenant_id: str,
        roles: tuple[str, ...],
        token_version: int,
    ) -> tuple[str, datetime]: ...

    def decode_access_token(self, token: str) -> AccessTokenClaims: ...
