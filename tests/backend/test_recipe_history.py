"""Real SQL view deduplication, keyset ordering and authenticated HTTP."""

from base64 import urlsafe_b64encode
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from safemeal.infrastructure.persistence.history_repository import (
    history,
    SqlAlchemyHistoryRepository,
)
from safemeal.infrastructure.persistence.recipe_repository import metadata, recipes
from safemeal.modules.interaction.application.history_service import HistoryService
from safemeal.modules.interaction.contracts.models import InteractionActor
from safemeal.shared.exceptions import (
    ApplicationError,
    InputValidationError,
    ResourceNotFoundError,
    DatabaseUnavailableError,
)


@pytest.fixture(autouse=True)
def configured_http(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")


@pytest.fixture
def storage(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'history.sqlite'}", connect_args={"timeout": 30}
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    metadata.create_all(engine)
    history.create(engine)
    with engine.begin() as connection:
        connection.execute(
            recipes.insert(), [{"id": n, "name": f"食谱{n}"} for n in range(1, 9)]
        )
    yield engine, HistoryService(SqlAlchemyHistoryRepository(engine))
    engine.dispose()


def actor(subject="one", tenant="default"):
    return InteractionActor(subject=subject, tenant_id=tenant)


def seed_history(engine, identity=None):
    identity = identity or actor()
    with engine.begin() as connection:
        for recipe_id in range(1, 9):
            connection.execute(
                history.insert().values(
                    tenant_id=identity.tenant_id,
                    subject=identity.subject,
                    recipe_id=recipe_id,
                    last_viewed_at=datetime(2025, 1, 1)
                    + timedelta(seconds=recipe_id // 3),
                )
            )


def test_record_revisit_deduplicates_and_returns_utc(storage):
    engine, service = storage
    seed_history(engine)
    first = service.record(1, actor())
    assert first.recipe_name == "食谱1"
    assert first.last_viewed_at.utcoffset() == timedelta(0)
    second = service.record(1, actor())
    assert second.last_viewed_at >= first.last_viewed_at
    page = service.list_recent(actor())
    assert page.items[0].recipe_id == 1
    assert not page.has_more and page.next_cursor is None
    with engine.connect() as connection:
        assert (
            connection.execute(select(func.count()).select_from(history)).scalar_one()
            == 8
        )


def test_equal_timestamp_keyset_all_pages(storage):
    engine, service = storage
    seed_history(engine)
    ids = []
    cursor = None
    while True:
        page = service.list_recent(actor(), limit=2, cursor=cursor)
        ids.extend(item.recipe_id for item in page.items)
        if not page.has_more:
            assert page.next_cursor is None
            break
        assert page.next_cursor != cursor
        cursor = page.next_cursor
    assert ids == [8, 7, 6, 5, 4, 3, 2, 1]


def test_live_timestamp_keyset_does_not_repeat_boundary(storage):
    _, service = storage
    for recipe_id in range(1, 5):
        service.record(recipe_id, actor())
    first = service.list_recent(actor(), limit=2)
    second = service.list_recent(actor(), limit=2, cursor=first.next_cursor)
    assert len({entry.recipe_id for entry in first.items + second.items}) == 4
    assert not second.has_more


def test_history_scope_case_spaces_and_delimiters(storage):
    _, service = storage
    identities = [
        actor(),
        actor("One"),
        actor("one "),
        actor("two"),
        actor("one", "other"),
        actor("b:c", "a"),
    ]
    for n, identity in enumerate(identities, 1):
        service.record(n, identity)
    for n, identity in enumerate(identities, 1):
        assert [entry.recipe_id for entry in service.list_recent(identity).items] == [n]
    assert service.list_recent(actor("c", "a:b")).items == ()


def test_concurrent_views_have_one_row_and_no_lost_recipes(storage):
    engine, service = storage
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: service.record(1, actor()), range(48)))
    with engine.connect() as connection:
        assert (
            connection.execute(select(func.count()).select_from(history)).scalar_one()
            == 1
        )
        timestamp = (
            connection.execute(select(history.c.last_viewed_at))
            .scalar_one()
            .replace(tzinfo=timezone.utc)
        )
    assert timestamp == max(item.last_viewed_at for item in results)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda n: service.record(n % 8 + 1, actor()), range(64)))
    assert len(service.list_recent(actor()).items) == 8


def test_clock_regression_does_not_move_history_backwards(storage):
    engine, service = storage
    future = datetime(2099, 1, 1)
    with engine.begin() as connection:
        connection.execute(
            history.insert().values(
                tenant_id="default", subject="one", recipe_id=1, last_viewed_at=future
            )
        )
    result = service.record(1, actor())
    assert result.last_viewed_at == future.replace(tzinfo=timezone.utc)


def test_page_with_revisit_between_reads(storage):
    engine, service = storage
    seed_history(engine)
    first = service.list_recent(actor(), limit=2)
    # An unseen recipe moves before the cursor; restart is necessary to see it.
    service.record(1, actor())
    second = service.list_recent(actor(), limit=50, cursor=first.next_cursor)
    assert not {entry.recipe_id for entry in first.items} & {
        entry.recipe_id for entry in second.items
    }
    assert service.list_recent(actor()).items[0].recipe_id == 1


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "not-base64!",
        urlsafe_b64encode(b"{}").decode(),
        urlsafe_b64encode(
            b'{"last_viewed_at":"2025-01-01T00:00:00","recipe_id":1}'
        ).decode(),
        "x" * 257,
    ],
)
def test_invalid_cursors_rejected(storage, cursor):
    with pytest.raises(InputValidationError):
        storage[1].list_recent(actor(), cursor=cursor)


def test_validation_and_missing_recipe_no_write(storage):
    engine, service = storage
    with pytest.raises(ResourceNotFoundError):
        service.record(999, actor())
    with pytest.raises(InputValidationError):
        service.record(0, actor())
    for limit in [0, 51]:
        with pytest.raises(InputValidationError):
            service.list_recent(actor(), limit=limit)
    with engine.connect() as connection:
        assert (
            connection.execute(select(func.count()).select_from(history)).scalar_one()
            == 0
        )


def test_unique_fk_and_recipe_deletion(storage):
    engine, service = storage
    service.record(1, actor())
    values = dict(
        tenant_id="default",
        subject="one",
        recipe_id=1,
        last_viewed_at=datetime.now(timezone.utc),
    )
    for invalid in [values, {**values, "recipe_id": 999}]:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(history.insert().values(**invalid))
    with engine.begin() as connection:
        connection.execute(recipes.delete().where(recipes.c.id == 1))
    assert service.list_recent(actor()).items == ()


def test_query_budget_and_history_index(storage):
    engine, service = storage
    seed_history(engine)
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def capture(_, __, statement, ___, ____, _____):
        statements.append(statement)

    service.list_recent(actor(), limit=2)
    assert len(statements) == 1  # Join + limit+1, no COUNT or N+1 hydration.
    statements.clear()
    service.record(1, actor())
    assert len(statements) == 3  # existence/name + upsert + timestamp
    with engine.connect() as connection:
        plan = connection.execute(
            text(
                "EXPLAIN QUERY PLAN SELECT recipe_id FROM recipe_view_history WHERE tenant_id='default' AND subject='one' ORDER BY last_viewed_at DESC, recipe_id DESC LIMIT 3"
            )
        ).all()
    assert any("ix_recipe_history_recent" in str(row) for row in plan)
    assert not any("TEMP B-TREE" in str(row) for row in plan)


def test_db_failure_maps_to_application_error(storage):
    engine, service = storage
    history.drop(engine)
    with pytest.raises(DatabaseUnavailableError):
        service.list_recent(actor())
    with pytest.raises(DatabaseUnavailableError):
        service.record(1, actor())


@pytest.fixture
def client(storage):
    from safemeal.interfaces import api_router
    from safemeal.interfaces.http.authentication import get_current_principal, Principal
    from safemeal.interfaces.http.dependencies import get_history_service

    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[get_current_principal] = lambda: Principal(subject="one")
    app.dependency_overrides[get_history_service] = lambda: storage[1]

    @app.exception_handler(ApplicationError)
    async def errors(_, exc):
        return JSONResponse(
            status_code=404 if isinstance(exc, ResourceNotFoundError) else 422,
            content={"code": exc.code},
        )

    with TestClient(app) as client:
        yield client


def test_http_history_route_order_tracking_and_spoofing(client, storage):
    assert client.get("/api/v1/recipes/history").json()["items"] == []
    for _ in range(2):
        response = client.put(
            "/api/v1/recipes/1/view",
            params={"subject": "victim", "tenant_id": "other"},
            json={"last_viewed_at": "2099-01-01", "subject": "victim"},
        )
        assert response.status_code == 200
    assert storage[1].list_recent(actor("victim")).items == ()
    response = client.get("/api/v1/recipes/history").json()
    assert (
        len(response["items"]) == 1 and response["items"][0]["recipe_name"] == "食谱1"
    )
    assert response["items"][0]["last_viewed_at"].endswith("Z")
    assert client.put("/api/v1/recipes/999/view").status_code == 404
    assert client.put("/api/v1/recipes/0/view").status_code == 422
    assert client.get("/api/v1/recipes/history?limit=51").status_code == 422
    assert client.get("/api/v1/recipes/history?cursor=bad!").status_code == 422


def test_migration_and_mysql_schema(tmp_path):
    path = Path(
        "safemeal/infrastructure/persistence/migrations/versions/20261008_0009_recipe_view_history.py"
    )
    spec = importlib.util.spec_from_file_location("history_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        with pytest.raises(RuntimeError, match="catalog"):
            migration.upgrade()
        metadata.create_all(connection)
        migration.upgrade()
        assert inspect(connection).get_pk_constraint("recipe_view_history")[
            "constrained_columns"
        ] == ["tenant_id", "subject", "recipe_id"]
        assert len(inspect(connection).get_indexes("recipe_view_history")) == 2
        assert (
            inspect(connection).get_foreign_keys("recipe_view_history")[0]["options"][
                "ondelete"
            ]
            == "CASCADE"
        )
        with pytest.raises(RuntimeError, match="Unexpected"):
            migration.upgrade()
        migration.downgrade()
        assert "recipe_view_history" not in inspect(connection).get_table_names()
        assert "recipes" in inspect(connection).get_table_names()
    engine.dispose()
    ddl = str(CreateTable(history).compile(dialect=mysql.dialect()))
    assert "DATETIME(6)" in ddl and ddl.count("utf8mb4_0900_bin") == 2


def test_missing_token_and_unsupported_identity(storage):
    from safemeal.interfaces.http.routers.history import router
    from safemeal.interfaces.http.authentication import get_current_principal, Principal
    from safemeal.interfaces.http.dependencies import (
        get_auth_service,
        get_history_service,
    )

    class UnusedAuth:
        def authenticate_access_token(self, token):
            pytest.fail("Missing token must be rejected before authenticating")

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/recipes")
    app.dependency_overrides[get_auth_service] = lambda: UnusedAuth()
    app.dependency_overrides[get_history_service] = lambda: storage[1]
    with TestClient(app) as client:
        assert client.get("/api/v1/recipes/history").status_code == 401
        assert client.put("/api/v1/recipes/1/view").status_code == 401
        app.dependency_overrides[get_current_principal] = lambda: Principal(
            subject="x" * 256
        )
        assert client.get("/api/v1/recipes/history").status_code == 403
        assert client.put("/api/v1/recipes/1/view").status_code == 403


def test_real_tokens_scope_record_and_cursor(storage, monkeypatch):
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
        get_history_service,
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
            secret="history-test-secret-more-than-32-characters",
            issuer="test",
            audience="test",
            access_token_minutes=5,
        ),
        refresh_token_days=7,
        default_tenant_id="default",
    )
    tokens = [
        auth.register(
            RegisterRequest(
                email=f"history{n}@example.com", password="correct-horse-123"
            )
        )
        for n in range(2)
    ]
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_history_service] = lambda: service
    with TestClient(app) as client:
        first = {"Authorization": f"Bearer {tokens[0].access_token}"}
        second = {"Authorization": f"Bearer {tokens[1].access_token}"}
        for recipe_id in [1, 2, 3]:
            assert (
                client.put(
                    f"/api/v1/recipes/{recipe_id}/view", headers=first
                ).status_code
                == 200
            )
        first_page = client.get("/api/v1/recipes/history?limit=1", headers=first).json()
        assert first_page["has_more"]
        # A valid cursor cannot carry identity authority across accounts.
        assert (
            client.get(
                "/api/v1/recipes/history",
                params={"cursor": first_page["next_cursor"]},
                headers=second,
            ).json()["items"]
            == []
        )
        client.put("/api/v1/recipes/8/view", headers=second)
        assert (
            len(client.get("/api/v1/recipes/history", headers=first).json()["items"])
            == 3
        )
        assert [
            item["recipe_id"]
            for item in client.get("/api/v1/recipes/history", headers=second).json()[
                "items"
            ]
        ] == [8]


def test_production_history_composition_errors_and_no_model(
    storage, monkeypatch, tmp_path
):
    from safemeal.config.settings import settings
    import safemeal.infrastructure.persistence.history_repository as persistence
    from safemeal.interfaces.http.authentication import get_current_principal, Principal

    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(settings, "AGENT_CHECKPOINT_DATABASE_URL", None)
    monkeypatch.setattr(
        settings, "AGENT_CHECKPOINT_PATH", str(tmp_path / "checkpoint.sqlite")
    )
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "ENABLE_LLM", True)
    monkeypatch.setattr(persistence, "get_engine", lambda: storage[0])
    from safemeal.main import create_application

    app = create_application()
    container = app.state.container

    def forbidden():
        pytest.fail("History must not initialize Agent/model or catalog cache")

    monkeypatch.setattr(container, "get_language_model_gateway", forbidden)
    monkeypatch.setattr(container, "_get_recipe_repository", forbidden)
    app.dependency_overrides[get_current_principal] = lambda: Principal(subject="one")
    with TestClient(app) as client:
        assert client.get("/api/v1/recipes/history").json()["items"] == []
        assert client.put("/api/v1/recipes/1/view").status_code == 200
        assert len(client.get("/api/v1/recipes/history").json()["items"]) == 1
        assert client.get("/api/v1/recipes/history?cursor=bad!").status_code == 422
        missing = client.put("/api/v1/recipes/999/view")
        assert (
            missing.status_code == 404
            and missing.json()["error"] == "resource_not_found"
        )
        assert client.put("/api/v1/recipes/9223372036854775808/view").status_code == 422
        history.drop(storage[0])
        assert client.get("/api/v1/recipes/history").status_code == 503
    assert container._language_model_gateway is None
    assert container._recipe_repository is None
