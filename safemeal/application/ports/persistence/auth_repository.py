"""Account and refresh-token persistence boundaries."""

from collections.abc import Callable
from datetime import datetime
from types import TracebackType
from typing import Protocol, TypeAlias

from safemeal.application.contracts.auth import UserCreate


class UserRecord(Protocol):
    id: str
    tenant_id: str
    email: str
    password_hash: str
    display_name: str | None
    status: str
    roles: tuple[str, ...] | list[str]
    token_version: int
    created_at: datetime
    updated_at: datetime | None


class RefreshTokenRecord(Protocol):
    id: str
    user_id: str
    token_hash: str
    expires_at: datetime
    revoked_at: datetime | None
    replaced_by_hash: str | None


class AuthRepository(Protocol):
    def create_user(self, data: UserCreate) -> UserRecord: ...
    def get_user(self, user_id: str) -> UserRecord | None: ...
    def get_user_by_email(self, tenant_id: str, email: str) -> UserRecord | None: ...
    def update_password_hash(self, user_id: str, password_hash: str) -> None: ...
    def increment_token_version(self, user_id: str) -> None: ...
    def create_refresh_token(
        self,
        *,
        token_id: str,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> RefreshTokenRecord: ...
    def get_refresh_token(self, token_hash: str) -> RefreshTokenRecord | None: ...
    def rotate_refresh_token(
        self,
        token_id: str,
        *,
        replaced_by_hash: str,
        revoked_at: datetime,
    ) -> None: ...
    def revoke_refresh_token(self, token_id: str, *, revoked_at: datetime) -> None: ...
    def revoke_all_refresh_tokens(self, user_id: str, *, revoked_at: datetime) -> None: ...


class AuthUnitOfWork(Protocol):
    @property
    def auth(self) -> AuthRepository: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def __enter__(self) -> "AuthUnitOfWork": ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


AuthUnitOfWorkFactory: TypeAlias = Callable[[], AuthUnitOfWork]
