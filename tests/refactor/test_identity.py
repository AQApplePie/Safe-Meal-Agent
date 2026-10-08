from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from safemeal.modules.identity.contracts import LoginRequest, RegisterRequest
from safemeal.shared.exceptions import (
    AuthenticationError,
    EmailAlreadyRegisteredError,
    InvalidAccessTokenError,
    InvalidRefreshTokenError,
)
from safemeal.modules.identity.application import AuthService
from safemeal.infrastructure.persistence.auth_repository import (
    SqlAlchemyAuthUnitOfWork,
)
from safemeal.infrastructure.persistence.database import Base
from safemeal.infrastructure.persistence.db.models import User
from safemeal.infrastructure.security import Argon2PasswordHasher, JwtTokenIssuer


@pytest.fixture
def identity() -> Iterator[tuple[AuthService, sessionmaker[Session]]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    service = AuthService(
        uow_factory=lambda: SqlAlchemyAuthUnitOfWork(session_factory=sessions),
        password_hasher=Argon2PasswordHasher(),
        token_issuer=JwtTokenIssuer(
            secret="test-secret-that-is-long-and-private",
            issuer="test-safemeal",
            audience="test-api",
            access_token_minutes=5,
        ),
        refresh_token_days=7,
        default_tenant_id="default",
    )
    try:
        yield service, sessions
    finally:
        engine.dispose()


def _register(service: AuthService):
    return service.register(
        RegisterRequest(
            email="  CHEF@example.com ",
            password="correct-horse-123",
            display_name="Chef",
        )
    )


def test_register_hashes_password_and_authenticates_access_token(identity):
    service, sessions = identity
    tokens = _register(service)

    assert tokens.user.email == "chef@example.com"
    assert tokens.user.display_name == "Chef"
    assert service.authenticate_access_token(tokens.access_token).id == tokens.user.id
    with sessions() as session:
        stored = session.get(User, tokens.user.id)
        assert stored is not None
        assert stored.password_hash != "correct-horse-123"
        assert stored.password_hash.startswith("$argon2")


def test_duplicate_registration_and_wrong_password_are_rejected(identity):
    service, _ = identity
    _register(service)

    with pytest.raises(EmailAlreadyRegisteredError):
        _register(service)
    with pytest.raises(AuthenticationError):
        service.login(
            LoginRequest(email="chef@example.com", password="incorrect-password")
        )


def test_refresh_rotation_detects_replay_and_invalidates_token_family(identity):
    service, _ = identity
    first = _register(service)
    rotated = service.refresh(first.refresh_token)

    assert rotated.refresh_token != first.refresh_token
    assert service.authenticate_access_token(rotated.access_token).id == first.user.id

    with pytest.raises(InvalidRefreshTokenError):
        service.refresh(first.refresh_token)
    with pytest.raises(InvalidRefreshTokenError):
        service.refresh(rotated.refresh_token)
    with pytest.raises(InvalidAccessTokenError):
        service.authenticate_access_token(rotated.access_token)


def test_logout_revokes_refresh_token(identity):
    service, _ = identity
    tokens = _register(service)

    service.logout(tokens.refresh_token)
    service.logout(tokens.refresh_token)

    with pytest.raises(InvalidRefreshTokenError):
        service.refresh(tokens.refresh_token)
