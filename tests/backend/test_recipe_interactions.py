"""Feature 2: real database, concurrent desired-state writes and authenticated HTTP."""

from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from safemeal.infrastructure.persistence.recipe_repository import metadata, recipes
from safemeal.infrastructure.persistence.reaction_repository import (
    SqlAlchemyReactionRepository,
    reactions,
)
from safemeal.modules.interaction.application.interaction_service import (
    InteractionService,
)
from safemeal.modules.interaction.contracts.models import InteractionActor
from safemeal.shared.exceptions import ApplicationError, ResourceNotFoundError


@pytest.fixture(autouse=True)
def configured_http(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")


@pytest.fixture
def storage(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'reactions.sqlite'}", connect_args={"timeout": 30}
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    metadata.create_all(engine)
    reactions.create(engine)
    with engine.begin() as connection:
        connection.execute(
            recipes.insert(), [{"id": 1, "name": "土豆"}, {"id": 2, "name": "鱼"}]
        )
    yield engine, InteractionService(SqlAlchemyReactionRepository(engine))
    engine.dispose()


def actor(subject="one", tenant="default"):
    return InteractionActor(subject=subject, tenant_id=tenant)


@pytest.mark.parametrize("kind", ["like", "favorite"])
def test_idempotency_independence_and_timestamp(storage, kind):
    engine, service = storage
    empty = service.read(1, actor())
    assert empty.like_count == empty.favorite_count == 0
    service.set_state(1, actor(), kind, True)
    with engine.connect() as connection:
        before = connection.execute(select(reactions.c.created_at)).scalar_one()
    for _ in range(3):
        result = service.set_state(1, actor(), kind, True)
        assert getattr(result, f"{kind}_count") == 1
    with engine.connect() as connection:
        assert connection.execute(select(reactions.c.created_at)).scalar_one() == before
    other = "favorite" if kind == "like" else "like"
    service.set_state(1, actor(), other, True)
    for _ in range(3):
        result = service.set_state(1, actor(), kind, False)
        assert getattr(result, f"{kind}_count") == 0
        assert getattr(result, f"{other}_count") == 1


def test_subject_tenant_and_recipe_isolation(storage):
    _, service = storage
    for identity in [actor(), actor("two"), actor("one", "other"), actor("One")]:
        service.set_state(1, identity, "like", True)
    assert service.read(1, actor()).like_count == 3
    assert service.read(1, actor("one", "other")).like_count == 1
    assert not service.read(1, actor("stranger")).liked
    assert service.read(2, actor()).like_count == 0
    service.set_state(1, actor(), "like", False)
    assert service.read(1, actor("two")).liked
    assert service.read(1, actor("One")).liked
    # Delimiters cannot alias another tenant/subject pair.
    service.set_state(1, actor("b:c", "a"), "favorite", True)
    assert not service.read(1, actor("c", "a:b")).favorited


@pytest.mark.parametrize("kind", ["like", "favorite"])
def test_concurrent_same_identity_and_many_users(storage, kind):
    engine, service = storage
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: service.set_state(1, actor(), kind, True), range(32)))
    assert getattr(service.read(1, actor()), f"{kind}_count") == 1
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda n: service.set_state(1, actor(str(n)), kind, True), range(24)
            )
        )
    assert getattr(service.read(1, actor()), f"{kind}_count") == 25
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: service.set_state(1, actor(), kind, False), range(32)))
    assert getattr(service.read(1, actor()), f"{kind}_count") == 24
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda n: service.set_state(1, actor(), kind, bool(n % 2)), range(32)
            )
        )
    service.set_state(1, actor(), kind, True)
    assert getattr(service.read(1, actor()), f"{kind}_count") == 25
    with engine.connect() as connection:
        assert (
            connection.execute(select(func.count()).select_from(reactions)).scalar_one()
            == 25
        )


@pytest.mark.parametrize("operation", ["read", "put", "delete"])
def test_missing_recipe_rejected_without_rows(storage, operation):
    engine, service = storage
    with pytest.raises(ResourceNotFoundError):
        if operation == "read":
            service.read(999, actor())
        else:
            service.set_state(999, actor(), "like", operation == "put")
    with engine.connect() as connection:
        assert (
            connection.execute(select(func.count()).select_from(reactions)).scalar_one()
            == 0
        )


def test_database_constraints_and_cascade(storage):
    engine, service = storage
    service.set_state(1, actor(), "like", True)
    values = dict(tenant_id="default", subject="one", recipe_id=1, kind="like")
    for invalid in [values, {**values, "recipe_id": 999}, {**values, "kind": "bogus"}]:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(reactions.insert().values(**invalid))
    with engine.begin() as connection:
        connection.execute(recipes.delete().where(recipes.c.id == 1))
    with engine.connect() as connection:
        assert (
            connection.execute(select(func.count()).select_from(reactions)).scalar_one()
            == 0
        )


@pytest.fixture
def client(storage):
    from safemeal.interfaces.http.routers.interactions import router
    from safemeal.interfaces.http.dependencies import get_interaction_service
    from safemeal.interfaces.http.authentication import get_current_principal, Principal
    from fastapi.responses import JSONResponse

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/recipes")
    app.dependency_overrides[get_interaction_service] = lambda: storage[1]
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        subject="one", tenant_id="default"
    )

    @app.exception_handler(ApplicationError)
    async def handler(_, error):
        return JSONResponse(status_code=404, content={"code": error.code})

    with TestClient(app) as result:
        yield result


@pytest.mark.parametrize("kind", ["like", "favorite"])
def test_http_desired_state_and_identity_spoof(client, storage, kind):
    url = f"/api/v1/recipes/1/{kind}"
    for _ in range(2):
        response = client.put(
            url,
            params={"user_id": "victim", "tenant_id": "other"},
            json={"subject": "victim"},
        )
        assert response.status_code == 200
        assert response.json()[f"{kind}_count"] == 1
    assert not getattr(
        storage[1].read(1, actor("victim")), "liked" if kind == "like" else "favorited"
    )
    assert client.get("/api/v1/recipes/1/interaction").status_code == 200
    for _ in range(2):
        assert client.delete(url).json()[f"{kind}_count"] == 0
    assert client.put(f"/api/v1/recipes/999/{kind}").status_code == 404
    assert client.put(f"/api/v1/recipes/0/{kind}").status_code == 422


def test_actual_auth_dependency_requires_token(storage):
    from safemeal.interfaces.http.routers.interactions import router
    from safemeal.interfaces.http.dependencies import (
        get_interaction_service,
        get_auth_service,
    )

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/recipes")
    app.dependency_overrides[get_interaction_service] = lambda: storage[1]

    class UnusedAuth:
        def authenticate_access_token(self, token):
            raise AssertionError("Missing token must be rejected first")

    app.dependency_overrides[get_auth_service] = lambda: UnusedAuth()
    with TestClient(app) as client:
        for method, suffix in [
            ("get", "interaction"),
            ("put", "like"),
            ("delete", "favorite"),
        ]:
            assert (
                getattr(client, method)(f"/api/v1/recipes/1/{suffix}").status_code
                == 401
            )


def test_migration_upgrade_downgrade_and_conflicts(tmp_path):
    path = Path(
        "safemeal/infrastructure/persistence/migrations/versions/20261008_0008_recipe_reactions.py"
    )
    spec = importlib.util.spec_from_file_location("reaction_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        with pytest.raises(RuntimeError, match="catalog"):
            module.upgrade()
        metadata.create_all(connection)
        module.upgrade()
        schema = inspect(connection)
        assert set(
            schema.get_pk_constraint("recipe_reactions")["constrained_columns"]
        ) == {"tenant_id", "subject", "recipe_id", "kind"}
        assert (
            schema.get_foreign_keys("recipe_reactions")[0]["options"]["ondelete"]
            == "CASCADE"
        )
        assert len(schema.get_indexes("recipe_reactions")) == 2
        with pytest.raises(RuntimeError, match="Unexpected"):
            module.upgrade()
        module.downgrade()
        assert "recipe_reactions" not in inspect(connection).get_table_names()
        assert "recipes" in inspect(connection).get_table_names()
    engine.dispose()


def test_mysql_schema_uses_case_sensitive_identity():
    ddl = str(CreateTable(reactions).compile(dialect=mysql.dialect()))
    assert ddl.count("utf8mb4_0900_bin") == 2
    assert "PRIMARY KEY (tenant_id, subject, recipe_id, kind)" in ddl
    assert "ON DELETE CASCADE" in ddl


def test_real_login_tokens_isolate_accounts(storage, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from safemeal.infrastructure.persistence.database import Base
    from safemeal.infrastructure.persistence.auth_repository import (
        SqlAlchemyAuthUnitOfWork,
    )
    from safemeal.infrastructure.security import Argon2PasswordHasher, JwtTokenIssuer
    from safemeal.modules.identity.application import AuthService
    from safemeal.modules.identity.contracts import RegisterRequest
    from safemeal.interfaces import api_router
    from safemeal.interfaces.http.dependencies import (
        get_auth_service,
        get_interaction_service,
    )
    from safemeal.config.settings import settings

    monkeypatch.setattr(settings, "ENABLE_OIDC", False)
    engine, service = storage
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    auth = AuthService(
        uow_factory=lambda: SqlAlchemyAuthUnitOfWork(session_factory=sessions),
        password_hasher=Argon2PasswordHasher(),
        token_issuer=JwtTokenIssuer(
            secret="reaction-test-secret-more-than-32-characters",
            issuer="test",
            audience="test",
            access_token_minutes=5,
        ),
        refresh_token_days=7,
        default_tenant_id="default",
    )
    tokens = [
        auth.register(
            RegisterRequest(email=f"user{n}@example.com", password="correct-horse-123")
        )
        for n in range(2)
    ]
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_interaction_service] = lambda: service
    with TestClient(app) as client:
        first = {"Authorization": f"Bearer {tokens[0].access_token}"}
        second = {"Authorization": f"Bearer {tokens[1].access_token}"}
        assert client.put("/api/v1/recipes/1/like", headers=first).json()["liked"]
        response = client.get("/api/v1/recipes/1/interaction", headers=second).json()
        assert not response["liked"] and response["like_count"] == 1
        client.delete("/api/v1/recipes/1/like", headers=second)
        assert client.get("/api/v1/recipes/1/interaction", headers=first).json()[
            "liked"
        ]


def test_oversized_authenticated_identity_rejected(client):
    from safemeal.interfaces.http.authentication import get_current_principal, Principal

    client.app.dependency_overrides[get_current_principal] = lambda: Principal(
        subject="x" * 256
    )
    assert client.put("/api/v1/recipes/1/like").status_code == 403


def test_production_composition_does_not_initialize_agent(
    storage, monkeypatch, tmp_path
):
    from safemeal.config.settings import settings
    import safemeal.infrastructure.persistence.reaction_repository as persistence
    from safemeal.interfaces.http.authentication import get_current_principal, Principal

    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(settings, "AGENT_CHECKPOINT_DATABASE_URL", None)
    monkeypatch.setattr(
        settings, "AGENT_CHECKPOINT_PATH", str(tmp_path / "checkpoint.sqlite")
    )
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(persistence, "get_engine", lambda: storage[0])
    from safemeal.main import create_application

    app = create_application()
    container = app.state.container

    def forbidden():
        pytest.fail("Interactions must not initialize model gateway")

    monkeypatch.setattr(container, "get_language_model_gateway", forbidden)
    app.dependency_overrides[get_current_principal] = lambda: Principal(subject="one")
    with TestClient(app) as client:
        assert client.put("/api/v1/recipes/1/like").json()["liked"]
        assert client.get("/api/v1/recipes/1/interaction").json()["like_count"] == 1
        missing = client.delete("/api/v1/recipes/999/favorite")
        assert missing.status_code == 404
        assert missing.json()["error"] == "resource_not_found"
    assert container._language_model_gateway is None
