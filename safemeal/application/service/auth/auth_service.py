"""Registration, login, refresh rotation and access-token authentication."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets
from uuid import uuid4

from safemeal.application.contracts.auth import (
    AccessTokenClaims,
    AuthTokens,
    LoginRequest,
    RegisterRequest,
    UserCreate,
    UserRead,
)
from safemeal.application.exceptions import (
    AccountDisabledError,
    AuthenticationError,
    EmailAlreadyRegisteredError,
    InvalidAccessTokenError,
    InvalidRefreshTokenError,
)
from safemeal.application.ports.persistence.auth_repository import (
    AuthUnitOfWorkFactory,
    UserRecord,
)
from safemeal.application.ports.security import PasswordHasher, TokenIssuer


class AuthService:
    def __init__(
        self,
        *,
        uow_factory: AuthUnitOfWorkFactory,
        password_hasher: PasswordHasher,
        token_issuer: TokenIssuer,
        refresh_token_days: int,
        default_tenant_id: str,
    ) -> None:
        self._uow_factory = uow_factory
        self._password_hasher = password_hasher
        self._token_issuer = token_issuer
        self._refresh_token_days = refresh_token_days
        self._default_tenant_id = default_tenant_id
        self._dummy_password_hash = password_hasher.hash(secrets.token_urlsafe(32))

    def register(self, request: RegisterRequest) -> AuthTokens:
        with self._uow_factory() as uow:
            if uow.auth.get_user_by_email(self._default_tenant_id, request.email):
                raise EmailAlreadyRegisteredError()
            user = uow.auth.create_user(
                UserCreate(
                    id=str(uuid4()),
                    tenant_id=self._default_tenant_id,
                    email=request.email,
                    password_hash=self._password_hasher.hash(request.password),
                    display_name=request.display_name,
                )
            )
            tokens = self._issue_tokens(uow, user)
            uow.commit()
            return tokens

    def login(self, request: LoginRequest) -> AuthTokens:
        with self._uow_factory() as uow:
            user = uow.auth.get_user_by_email(self._default_tenant_id, request.email)
            password_hash = (
                user.password_hash if user is not None else self._dummy_password_hash
            )
            password_matches = self._password_hasher.verify(
                password_hash, request.password
            )
            if user is None or not password_matches:
                raise AuthenticationError()
            self._require_active(user)
            if self._password_hasher.needs_rehash(user.password_hash):
                uow.auth.update_password_hash(
                    user.id, self._password_hasher.hash(request.password)
                )
            tokens = self._issue_tokens(uow, user)
            uow.commit()
            return tokens

    def refresh(self, raw_token: str) -> AuthTokens:
        token_hash = self._refresh_hash(raw_token)
        now = datetime.now(timezone.utc)
        with self._uow_factory() as uow:
            stored = uow.auth.get_refresh_token(token_hash)
            if stored is None:
                raise InvalidRefreshTokenError()
            user = uow.auth.get_user(stored.user_id)
            if user is None:
                raise InvalidRefreshTokenError()
            if stored.revoked_at is not None:
                # A rotated token was reused. Revoke the complete token family and
                # invalidate outstanding access tokens for this user.
                if stored.replaced_by_hash is not None:
                    uow.auth.revoke_all_refresh_tokens(user.id, revoked_at=now)
                    uow.auth.increment_token_version(user.id)
                    uow.commit()
                raise InvalidRefreshTokenError()
            if self._as_utc(stored.expires_at) <= now:
                uow.auth.revoke_refresh_token(stored.id, revoked_at=now)
                uow.commit()
                raise InvalidRefreshTokenError()
            self._require_active(user)
            raw_next, next_hash = self._new_refresh_token()
            uow.auth.rotate_refresh_token(
                stored.id, replaced_by_hash=next_hash, revoked_at=now
            )
            tokens = self._issue_tokens(
                uow, user, raw_refresh_token=raw_next, refresh_hash=next_hash
            )
            uow.commit()
            return tokens

    def logout(self, raw_token: str) -> None:
        token_hash = self._refresh_hash(raw_token)
        with self._uow_factory() as uow:
            stored = uow.auth.get_refresh_token(token_hash)
            if stored is not None and stored.revoked_at is None:
                uow.auth.revoke_refresh_token(
                    stored.id, revoked_at=datetime.now(timezone.utc)
                )
                uow.commit()

    def authenticate_access_token(self, raw_token: str) -> UserRead:
        try:
            claims: AccessTokenClaims = self._token_issuer.decode_access_token(raw_token)
        except Exception as exc:
            raise InvalidAccessTokenError() from exc
        with self._uow_factory() as uow:
            user = uow.auth.get_user(claims.subject)
            if user is None or user.tenant_id != claims.tenant_id:
                raise InvalidAccessTokenError()
            self._require_active(user)
            if user.token_version != claims.token_version:
                raise InvalidAccessTokenError()
            return self._read_user(user)

    def get_user(self, user_id: str) -> UserRead:
        with self._uow_factory() as uow:
            user = uow.auth.get_user(user_id)
            if user is None:
                raise InvalidAccessTokenError()
            self._require_active(user)
            return self._read_user(user)

    def _issue_tokens(
        self,
        uow,
        user: UserRecord,
        *,
        raw_refresh_token: str | None = None,
        refresh_hash: str | None = None,
    ) -> AuthTokens:
        access_token, access_expires_at = self._token_issuer.issue_access_token(
            subject=user.id,
            tenant_id=user.tenant_id,
            roles=tuple(user.roles),
            token_version=user.token_version,
        )
        if raw_refresh_token is None or refresh_hash is None:
            raw_refresh_token, refresh_hash = self._new_refresh_token()
        uow.auth.create_refresh_token(
            token_id=str(uuid4()),
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=self._refresh_token_days),
        )
        expires_in = max(
            1,
            int((access_expires_at - datetime.now(timezone.utc)).total_seconds()),
        )
        return AuthTokens(
            access_token=access_token,
            refresh_token=raw_refresh_token,
            expires_in=expires_in,
            user=self._read_user(user),
        )

    @staticmethod
    def _read_user(user: UserRecord) -> UserRead:
        return UserRead.model_validate(user)

    @staticmethod
    def _require_active(user: UserRecord) -> None:
        if user.status != "active":
            raise AccountDisabledError()

    @staticmethod
    def _new_refresh_token() -> tuple[str, str]:
        raw = secrets.token_urlsafe(48)
        return raw, AuthService._refresh_hash(raw)

    @staticmethod
    def _refresh_hash(raw_token: str) -> str:
        return sha256(raw_token.encode("utf-8")).hexdigest()

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
