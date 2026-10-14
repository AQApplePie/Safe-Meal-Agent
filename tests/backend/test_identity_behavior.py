"""Personal favorites and batch states through real SQL, JWT and OIDC signatures."""

from datetime import datetime, timedelta, timezone
import importlib.util
from io import BytesIO
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import jwt
import pytest
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.orm import sessionmaker

from safemeal.infrastructure.persistence.database import Base
from safemeal.infrastructure.persistence.db.models import User
from safemeal.infrastructure.persistence.auth_repository import SqlAlchemyAuthUnitOfWork
from safemeal.infrastructure.persistence.recipe_repository import metadata, recipes
from safemeal.infrastructure.persistence.reaction_repository import (
    reactions,
    SqlAlchemyReactionRepository,
)
from safemeal.infrastructure.security import Argon2PasswordHasher, JwtTokenIssuer
from safemeal.modules.identity.application import AuthService
from safemeal.modules.interaction.application.interaction_service import (
    InteractionService,
)
from safemeal.modules.interaction.contracts.models import InteractionActor
from safemeal.shared.exceptions import (
    ApplicationError,
    AuthenticationError,
    AccountDisabledError,
    DatabaseOperationError,
    InputValidationError,
)

SECRET = "behavior-test-secret-longer-than-32-characters"


@pytest.fixture(autouse=True)
def configured_http(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")


@pytest.fixture
def storage(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'behavior.sqlite'}")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    metadata.create_all(engine)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            recipes.insert(), [{"id": n, "name": f"食谱{n}"} for n in range(1, 7)]
        )
        connection.execute(
            reactions.insert(),
            [
                dict(
                    tenant_id="default",
                    subject="alice",
                    recipe_id=n,
                    kind="favorite",
                    created_at=datetime(2025, 1, 1, 0, 0, n // 2),
                )
                for n in range(1, 4)
            ]
            + [
                dict(
                    tenant_id="default",
                    subject="alice",
                    recipe_id=4,
                    kind="like",
                    created_at=datetime(2025, 1, 1),
                ),
                dict(
                    tenant_id="default",
                    subject="bob",
                    recipe_id=1,
                    kind="favorite",
                    created_at=datetime(2025, 1, 1),
                ),
                dict(
                    tenant_id="default",
                    subject="bob",
                    recipe_id=1,
                    kind="like",
                    created_at=datetime(2025, 1, 1),
                ),
                dict(
                    tenant_id="other",
                    subject="alice",
                    recipe_id=6,
                    kind="favorite",
                    created_at=datetime(2025, 1, 1),
                ),
            ],
        )
    yield engine, InteractionService(SqlAlchemyReactionRepository(engine))
    engine.dispose()


def actor(subject="alice", tenant="default"):
    return InteractionActor(subject=subject, tenant_id=tenant)


def test_personal_favorites_order_pagination_and_cancel(storage):
    _, service = storage
    first = service.list_favorites(actor(), limit=2)
    assert [item.recipe_id for item in first.items] == [3, 2]
    assert first.has_more
    second = service.list_favorites(actor(), offset=2, limit=2)
    assert [item.recipe_id for item in second.items] == [1] and not second.has_more
    assert service.list_favorites(actor("unknown")).items == ()
    assert [
        item.recipe_id for item in service.list_favorites(actor(tenant="other")).items
    ] == [6]
    service.set_state(3, actor(), "favorite", False)
    assert [item.recipe_id for item in service.list_favorites(actor()).items] == [2, 1]
    service.set_state(3, actor(), "favorite", True)
    assert service.list_favorites(actor()).items[0].recipe_id == 3


def test_batch_preserves_input_deduplicates_and_reports_missing(storage):
    _, service = storage
    result = service.read_many((4, 1, 5, 999, 4, 999), actor())
    assert [item.recipe_id for item in result.items] == [4, 1, 5]
    assert result.missing_recipe_ids == (999,)
    first = result.items[0]
    assert first.liked and not first.favorited and first.like_count == 1
    shared = result.items[1]
    assert not shared.liked and shared.favorited
    assert shared.like_count == 1 and shared.favorite_count == 2
    empty = result.items[2]
    assert not empty.liked and not empty.favorited
    assert empty.like_count == empty.favorite_count == 0


def test_batch_tenant_and_personal_state_isolation(storage):
    _, service = storage
    other = service.read_many((1, 6), actor(tenant="other"))
    assert other.items[0].like_count == other.items[0].favorite_count == 0
    assert other.items[1].favorited and other.items[1].favorite_count == 1
    bob = service.read_many((1, 2), actor("bob"))
    assert bob.items[0].liked and bob.items[0].favorited
    assert not bob.items[1].favorited
    assert bob.items[1].favorite_count == 1


def test_batch_and_favorites_are_single_queries_and_use_index(storage):
    engine, service = storage
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def capture(_, __, statement, ___, ____, _____):
        statements.append(statement)

    service.read_many(tuple(range(1, 101)), actor())
    assert len(statements) == 1
    statements.clear()
    service.list_favorites(actor(), limit=2)
    assert len(statements) == 1
    with engine.connect() as connection:
        plan = connection.execute(
            text(
                "EXPLAIN QUERY PLAN SELECT recipe_id FROM recipe_reactions WHERE tenant_id='default' AND subject='alice' AND kind='favorite' ORDER BY created_at DESC, recipe_id DESC LIMIT 3"
            )
        ).all()
    assert any("ix_recipe_reactions_favorites" in str(row) for row in plan)
    assert not any("TEMP B-TREE" in str(row) for row in plan)


@pytest.mark.parametrize(
    "ids", [(), (0,), (2147483648,), (True,), tuple(range(1, 102))]
)
def test_batch_bounds(storage, ids):
    with pytest.raises(InputValidationError):
        storage[1].read_many(ids, actor())


def test_favorites_bounds_and_deleted_recipe(storage):
    engine, service = storage
    for offset, limit in [(-1, 20), (10001, 20), (0, 0), (0, 51)]:
        with pytest.raises(InputValidationError):
            service.list_favorites(actor(), offset, limit)
    with engine.begin() as connection:
        connection.execute(recipes.delete().where(recipes.c.id == 3))
    assert [item.recipe_id for item in service.list_favorites(actor()).items] == [2, 1]
    assert service.read_many((3,), actor()).missing_recipe_ids == (3,)


@pytest.fixture
def auth(storage):
    sessions = sessionmaker(bind=storage[0], expire_on_commit=False)
    service = AuthService(
        uow_factory=lambda: SqlAlchemyAuthUnitOfWork(session_factory=sessions),
        password_hasher=Argon2PasswordHasher(),
        token_issuer=JwtTokenIssuer(
            secret=SECRET, issuer="test", audience="test", access_token_minutes=5
        ),
        refresh_token_days=7,
        default_tenant_id="default",
    )
    return service, sessions


@pytest.fixture
def client(storage, auth, monkeypatch):
    from safemeal.config.settings import settings
    from safemeal.interfaces import api_router
    from safemeal.interfaces.http.dependencies import (
        get_auth_service,
        get_interaction_service,
    )

    monkeypatch.setattr(settings, "ENABLE_OIDC", False)
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[get_auth_service] = lambda: auth[0]
    app.dependency_overrides[get_interaction_service] = lambda: storage[1]

    @app.exception_handler(ApplicationError)
    async def errors(_, exc):
        status = (
            403
            if isinstance(exc, AccountDisabledError)
            else 401
            if isinstance(exc, AuthenticationError)
            else 503
            if isinstance(exc, DatabaseOperationError)
            else 422
        )
        return JSONResponse(status_code=status, content={"error": exc.code})

    with TestClient(app) as client:
        yield client


def register(client, email):
    result = client.post(
        "/api/v1/auth/register", json={"email": email, "password": "correct-horse-123"}
    )
    assert result.status_code == 201
    data = result.json()
    return data, {"Authorization": "Bearer " + data["access_token"]}


def test_real_registration_login_me_and_private_behavior(client):
    first, headers = register(client, "first@example.com")
    second, other = register(client, "second@example.com")
    assert (
        client.get("/api/v1/auth/me", headers=headers).json()["subject"]
        == first["user"]["id"]
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "FIRST@example.com", "password": "correct-horse-123"},
    )
    assert login.status_code == 200
    assert client.put("/api/v1/recipes/2/favorite", headers=headers).status_code == 200
    page = client.get(
        "/api/v1/recipes/favorites",
        headers=headers,
        params={"subject": second["user"]["id"], "tenant_id": "other"},
    ).json()
    assert [item["recipe_id"] for item in page["items"]] == [2]
    assert client.get("/api/v1/recipes/favorites", headers=other).json()["items"] == []
    result = client.post(
        "/api/v1/recipes/interactions/query",
        headers=other,
        json={"recipe_ids": [2, 999]},
    ).json()
    assert not result["items"][0]["favorited"]
    assert result["missing_recipe_ids"] == [999]
    assert client.delete("/api/v1/recipes/2/favorite", headers=other).status_code == 200
    assert client.get("/api/v1/recipes/favorites", headers=headers).json()["items"]


@pytest.mark.parametrize(
    "body",
    [
        {"recipe_ids": []},
        {"recipe_ids": [True]},
        {"recipe_ids": ["1"]},
        {"recipe_ids": [1], "tenant_id": "other"},
        {"recipe_ids": list(range(1, 102))},
    ],
)
def test_http_rejects_unbounded_or_spoofed_batch(client, body):
    _, headers = register(client, "bounds@example.com")
    assert (
        client.post(
            "/api/v1/recipes/interactions/query", headers=headers, json=body
        ).status_code
        == 422
    )


def test_missing_auth_and_invalid_tokens(client):
    assert client.get("/api/v1/recipes/favorites").status_code == 401
    assert (
        client.post(
            "/api/v1/recipes/interactions/query", json={"recipe_ids": [1]}
        ).status_code
        == 401
    )
    _, headers = register(client, "token@example.com")
    payload = jwt.decode(
        headers["Authorization"].split()[1],
        SECRET,
        algorithms=["HS256"],
        audience="test",
        issuer="test",
    )
    for changes in [
        {"exp": 0},
        {"tid": "other"},
        {"aud": "wrong"},
        {"iss": "wrong"},
        {"typ": "refresh"},
    ]:
        token = jwt.encode({**payload, **changes}, SECRET, algorithm="HS256")
        invalid = {"Authorization": "Bearer " + token}
        assert (
            client.get("/api/v1/recipes/favorites", headers=invalid).status_code == 401
        )
        assert (
            client.post(
                "/api/v1/recipes/interactions/query",
                headers=invalid,
                json={"recipe_ids": [1]},
            ).status_code
            == 401
        )


def test_disabled_account_and_token_version_block_behavior(client, auth):
    data, headers = register(client, "disabled@example.com")
    with auth[1].begin() as session:
        user = session.get(User, data["user"]["id"])
        user.status = "disabled"
    assert client.get("/api/v1/recipes/favorites", headers=headers).status_code == 403
    assert (
        client.post(
            "/api/v1/recipes/interactions/query",
            headers=headers,
            json={"recipe_ids": [1]},
        ).status_code
        == 403
    )
    with auth[1].begin() as session:
        user = session.get(User, data["user"]["id"])
        user.status = "active"
        user.token_version += 1
    assert client.get("/api/v1/recipes/favorites", headers=headers).status_code == 401


def test_refresh_replay_and_logout_policy(client):
    data, headers = register(client, "refresh@example.com")
    rotated = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]}
    )
    assert rotated.status_code == 200
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]}
        ).status_code
        == 401
    )
    assert client.get("/api/v1/recipes/favorites", headers=headers).status_code == 401
    newer, new_headers = register(client, "logout@example.com")
    assert (
        client.post(
            "/api/v1/auth/logout", json={"refresh_token": newer["refresh_token"]}
        ).status_code
        == 204
    )
    assert (
        client.post(
            "/api/v1/auth/refresh", json={"refresh_token": newer["refresh_token"]}
        ).status_code
        == 401
    )
    # Existing contract: logout revokes this refresh token; short-lived access remains.
    assert (
        client.get("/api/v1/recipes/favorites", headers=new_headers).status_code == 200
    )


@pytest.fixture
def oidc(monkeypatch):
    from safemeal.config.settings import settings
    from safemeal.interfaces.http.authentication import _jwks_client
    import jwt.jwks_client as jwks

    _jwks_client.cache_clear()
    monkeypatch.setattr(settings, "ENABLE_OIDC", True)
    monkeypatch.setattr(settings, "OIDC_ISSUER", "https://identity.test")
    monkeypatch.setattr(settings, "OIDC_AUDIENCE", "safemeal-test")
    monkeypatch.setattr(settings, "OIDC_JWKS_URL", "https://identity.test/jwks")
    monkeypatch.setattr(settings, "OIDC_TENANT_CLAIM", "tid")
    monkeypatch.setattr(settings, "OIDC_ALGORITHMS", "RS256")
    keys = [
        rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(2)
    ]
    payload = {"keys": []}
    calls = []

    def install(index):
        item = jwt.algorithms.RSAAlgorithm.to_jwk(
            keys[index].public_key(), as_dict=True
        )
        item.update(kid=f"key{index}", use="sig", alg="RS256")
        payload["keys"] = [item]

    install(0)

    def urlopen(request, **kwargs):
        calls.append(request.full_url)
        return BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(jwks.urllib.request, "urlopen", urlopen)

    def token(changes=None, index=0):
        now = datetime.now(timezone.utc)
        claims = dict(
            sub="alice",
            tid="default",
            iss="https://identity.test",
            aud="safemeal-test",
            iat=now,
            exp=now + timedelta(minutes=5),
        )
        return jwt.encode(
            {**claims, **(changes or {})},
            keys[index],
            algorithm="RS256",
            headers={"kid": f"key{index}"},
        )

    yield token, install, calls
    _jwks_client.cache_clear()


def test_oidc_signed_identity_scopes_favorites_and_reuses_jwks(client, oidc):
    token, _, calls = oidc
    headers = {"Authorization": "Bearer " + token()}
    for _ in range(2):
        assert [
            item["recipe_id"]
            for item in client.get("/api/v1/recipes/favorites", headers=headers).json()[
                "items"
            ]
        ] == [3, 2, 1]
    assert len(calls) == 1
    other = {"Authorization": "Bearer " + token({"tid": "other"})}
    assert [
        item["recipe_id"]
        for item in client.get("/api/v1/recipes/favorites", headers=other).json()[
            "items"
        ]
    ] == [6]
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "x@example.com", "password": "any"}
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "changes,status",
    [
        ({"sub": None}, 401),
        ({"sub": 123}, 401),
        ({"sub": " "}, 401),
        ({"tid": 123}, 403),
        ({"tid": None}, 403),
        ({"tid": " "}, 403),
        ({"aud": "wrong"}, 401),
        ({"iss": "wrong"}, 401),
        ({"exp": 0}, 401),
    ],
)
def test_oidc_invalid_claims_do_not_alias_accounts(client, oidc, changes, status):
    token, _, _ = oidc
    assert (
        client.get(
            "/api/v1/recipes/favorites",
            headers={"Authorization": "Bearer " + token(changes)},
        ).status_code
        == status
    )


def test_oidc_exact_tenant_and_key_rotation(client, oidc):
    token, install, calls = oidc
    assert (
        client.get(
            "/api/v1/recipes/favorites", headers={"Authorization": "Bearer " + token()}
        ).status_code
        == 200
    )
    spaced = client.get(
        "/api/v1/recipes/favorites",
        headers={"Authorization": "Bearer " + token({"tid": "default "})},
    )
    assert spaced.json()["items"] == []
    install(1)
    assert (
        client.get(
            "/api/v1/recipes/favorites",
            headers={"Authorization": "Bearer " + token(index=1)},
        ).status_code
        == 200
    )
    assert len(calls) == 2


def test_new_index_migration_preserves_reactions(tmp_path):
    def load(filename, name):
        spec = importlib.util.spec_from_file_location(
            name,
            Path("safemeal/infrastructure/persistence/migrations/versions") / filename,
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    previous = load("20261008_0008_recipe_reactions.py", "previous_reactions")
    migration = load("20261008_0011_personal_favorites_index.py", "favorites_index")
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    with engine.begin() as connection:
        previous.op = migration.op = Operations(MigrationContext.configure(connection))
        with pytest.raises(RuntimeError, match="reactions"):
            migration.upgrade()
        metadata.create_all(connection)
        previous.upgrade()
        connection.execute(recipes.insert().values(id=1, name="one"))
        connection.execute(
            reactions.insert().values(
                tenant_id="default", subject="alice", recipe_id=1, kind="favorite"
            )
        )
        migration.upgrade()
        assert len(inspect(connection).get_indexes("recipe_reactions")) == 3
        with pytest.raises(RuntimeError, match="Unexpected"):
            migration.upgrade()
        migration.downgrade()
        assert len(inspect(connection).get_indexes("recipe_reactions")) == 2
        assert connection.execute(select(reactions.c.kind)).scalar_one() == "favorite"
    engine.dispose()


def test_production_behavior_composition_and_db_error(
    storage, auth, monkeypatch, tmp_path
):
    from safemeal.config.settings import settings
    import safemeal.infrastructure.persistence.reaction_repository as persistence

    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(settings, "AGENT_CHECKPOINT_DATABASE_URL", None)
    monkeypatch.setattr(
        settings, "AGENT_CHECKPOINT_PATH", str(tmp_path / "checkpoint.sqlite")
    )
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "RECIPE_RANKING_REDIS_URL", None)
    monkeypatch.setattr(settings, "ENABLE_OIDC", False)
    monkeypatch.setattr(settings, "ENABLE_LLM", True)
    monkeypatch.setattr(persistence, "get_engine", lambda: storage[0])
    from safemeal.main import create_application

    app = create_application()
    container = app.state.container
    container._auth_service = auth[0]

    def forbidden():
        pytest.fail(
            "Personal behavior must not initialize model or public recipe cache"
        )

    monkeypatch.setattr(container, "get_language_model_gateway", forbidden)
    monkeypatch.setattr(container, "_get_recipe_repository", forbidden)
    with TestClient(app) as client:
        _, headers = register(client, "production@example.com")
        assert (
            client.put("/api/v1/recipes/2/favorite", headers=headers).status_code == 200
        )
        assert [
            item["recipe_id"]
            for item in client.get("/api/v1/recipes/favorites", headers=headers).json()[
                "items"
            ]
        ] == [2]
        result = client.post(
            "/api/v1/recipes/interactions/query",
            headers=headers,
            json={"recipe_ids": [2, 999]},
        )
        assert result.status_code == 200 and result.json()["missing_recipe_ids"] == [
            999
        ]
        reactions.drop(storage[0])
        assert (
            client.get("/api/v1/recipes/favorites", headers=headers).status_code == 503
        )
        assert (
            client.post(
                "/api/v1/recipes/interactions/query",
                headers=headers,
                json={"recipe_ids": [1]},
            ).status_code
            == 503
        )
    assert (
        container._language_model_gateway is None
        and container._recipe_repository is None
    )


def test_conversation_identity_keys_preserve_local_and_separate_ambiguous_identities():
    from safemeal.interfaces.http.authentication import Principal

    assert (
        Principal(subject="account-id", tenant_id="tenant-id").storage_subject
        == "tenant-id:account-id"
    )
    first = Principal(subject="b:c", tenant_id="a").storage_subject
    second = Principal(subject="c", tenant_id="a:b").storage_subject
    assert first != second and ":" not in first and ":" not in second
    values = [
        Principal(subject=value).storage_subject
        for value in ["alice", "Alice", "e", "é", "alice ", "x" * 255]
    ]
    assert len(set(item.casefold() for item in values)) == len(values)
    assert all(len(item) <= 255 for item in values)
    assert (
        Principal(subject="Alice").storage_subject
        == Principal(subject="Alice").storage_subject
    )


def test_chat_http_uses_distinct_keys_for_signed_oidc_identities(client, oidc):
    from safemeal.interfaces.http.dependencies import get_chat_session_service

    token, _, _ = oidc

    class Sessions:
        seen = []

        def list_sessions(self, *, user_id, skip, limit, active_only):
            self.seen.append(user_id)
            return []

    sessions = Sessions()
    client.app.dependency_overrides[get_chat_session_service] = lambda: sessions
    for claims in [
        {"tid": "a", "sub": "b:c"},
        {"tid": "a:b", "sub": "c"},
        {"tid": "default", "sub": "Alice"},
        {"tid": "default", "sub": "alice"},
    ]:
        response = client.get(
            "/api/v1/chat/sessions",
            headers={"Authorization": "Bearer " + token(claims)},
        )
        assert response.status_code == 200
    assert len(set(item.casefold() for item in sessions.seen)) == 4
