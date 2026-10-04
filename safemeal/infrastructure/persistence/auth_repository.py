"""SQLAlchemy account and refresh-token repositories."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from types import TracebackType
from typing import cast

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from safemeal.application.contracts.auth import UserCreate
from safemeal.application.exceptions import EmailAlreadyRegisteredError
from safemeal.application.ports.persistence.auth_repository import AuthUnitOfWork
from safemeal.infrastructure.persistence.database import session_scope
from safemeal.infrastructure.persistence.db.models import RefreshToken, User


class SqlAlchemyAuthRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_user(self, data: UserCreate) -> User:
        entity = User(**data.model_dump(), status="active", roles=[], token_version=0)
        self._session.add(entity)
        try:
            self._session.flush()
        except IntegrityError as exc:
            raise EmailAlreadyRegisteredError() from exc
        return entity

    def get_user(self, user_id: str) -> User | None:
        return self._session.get(User, user_id)

    def get_user_by_email(self, tenant_id: str, email: str) -> User | None:
        return (
            self._session.query(User)
            .filter(User.tenant_id == tenant_id, User.email == email)
            .one_or_none()
        )

    def update_password_hash(self, user_id: str, password_hash: str) -> None:
        self._session.query(User).filter(User.id == user_id).update(
            {User.password_hash: password_hash}, synchronize_session=False
        )
        self._session.flush()

    def increment_token_version(self, user_id: str) -> None:
        self._session.query(User).filter(User.id == user_id).update(
            {User.token_version: User.token_version + 1}, synchronize_session=False
        )
        self._session.flush()

    def create_refresh_token(
        self,
        *,
        token_id: str,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> RefreshToken:
        entity = RefreshToken(
            id=token_id,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self._session.add(entity)
        self._session.flush()
        return entity

    def get_refresh_token(self, token_hash: str) -> RefreshToken | None:
        return (
            self._session.query(RefreshToken)
            .filter(RefreshToken.token_hash == token_hash)
            .with_for_update()
            .one_or_none()
        )

    def rotate_refresh_token(
        self,
        token_id: str,
        *,
        replaced_by_hash: str,
        revoked_at: datetime,
    ) -> None:
        self._session.query(RefreshToken).filter(RefreshToken.id == token_id).update(
            {
                RefreshToken.revoked_at: revoked_at,
                RefreshToken.replaced_by_hash: replaced_by_hash,
            },
            synchronize_session=False,
        )
        self._session.flush()

    def revoke_refresh_token(self, token_id: str, *, revoked_at: datetime) -> None:
        self._session.query(RefreshToken).filter(
            RefreshToken.id == token_id, RefreshToken.revoked_at.is_(None)
        ).update({RefreshToken.revoked_at: revoked_at}, synchronize_session=False)
        self._session.flush()

    def revoke_all_refresh_tokens(self, user_id: str, *, revoked_at: datetime) -> None:
        (
            self._session.query(RefreshToken)
            .filter(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .update({RefreshToken.revoked_at: revoked_at}, synchronize_session=False)
        )
        self._session.flush()


class SqlAlchemyAuthUnitOfWork:
    def __init__(self, *, session_factory: Callable[[], Session] | None = None) -> None:
        self._session_factory = session_factory
        self._scope: AbstractContextManager[Session] | None = None
        self._session: Session | None = None
        self._auth: SqlAlchemyAuthRepository | None = None

    @property
    def auth(self) -> SqlAlchemyAuthRepository:
        if self._auth is None:
            raise RuntimeError("auth Unit of Work is not active")
        return self._auth

    def __enter__(self) -> "SqlAlchemyAuthUnitOfWork":
        scope = session_scope(commit=False, session_factory=self._session_factory)
        self._session = scope.__enter__()
        self._scope = scope
        self._auth = SqlAlchemyAuthRepository(self._session)
        return self

    def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("auth Unit of Work is not active")
        self._session.commit()

    def rollback(self) -> None:
        if self._session is not None:
            self._session.rollback()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._scope is None:
            raise RuntimeError("auth Unit of Work is not active")
        try:
            self._scope.__exit__(exc_type, exc_value, traceback)
        finally:
            self._scope = None
            self._session = None
            self._auth = None


def sqlalchemy_auth_unit_of_work() -> AuthUnitOfWork:
    return cast(AuthUnitOfWork, SqlAlchemyAuthUnitOfWork())


__all__ = [
    "SqlAlchemyAuthRepository",
    "SqlAlchemyAuthUnitOfWork",
    "sqlalchemy_auth_unit_of_work",
]
