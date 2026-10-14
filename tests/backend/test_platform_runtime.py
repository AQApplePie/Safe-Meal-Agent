"""Protect standalone runtime and shared HTTP behavior without Agent packages."""

from pathlib import Path
import os
import subprocess
import sys

import pytest
from pydantic import ValidationError
from safemeal.config.platform import PlatformSettings

ROOT = Path(__file__).resolve().parents[2]


def test_standalone_http_without_agent_imports(tmp_path):
    code = """
import importlib.abc, sys
class NoAgent(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("safemeal.agent", "langgraph", "langchain", "openai", "pymilvus", "neo4j")):
            raise ImportError("Forbidden dependency: " + fullname)
sys.meta_path.insert(0, NoAgent())
from safemeal.config.platform import PlatformSettings
from safemeal.bootstrap.composition.platform_application import create_platform_application
from safemeal.infrastructure.persistence.database import get_engine
from safemeal.infrastructure.persistence.recipe_repository import metadata, recipes, cuisines, ingredients, recipe_ingredients, recipe_steps
from safemeal.infrastructure.persistence.database import Base
import safemeal.infrastructure.persistence.db.models
from fastapi.testclient import TestClient
from scripts.platform_smoke import run_smoke
app = create_platform_application(PlatformSettings())
engine = get_engine()
metadata.create_all(engine)
with engine.begin() as connection:
    connection.execute(cuisines.insert().values(id=1, name="家常"))
    connection.execute(recipes.insert().values(id=1, name="演示菜", description="示例", servings=2, total_time=10, difficulty="easy", cuisine_id=1, total_calories=100))
    connection.execute(ingredients.insert().values(id=1, name="土豆"))
    connection.execute(recipe_ingredients.insert().values(id=1, recipe_id=1, ingredient_id=1, quantity="100", unit="g", is_main=True, ingredient_type="main"))
    connection.execute(recipe_steps.insert().values(id=1, recipe_id=1, step_number=1, action="蒸", instruction="蒸熟土豆"))
Base.metadata.create_all(engine)
with TestClient(app) as client:
    result = run_smoke(client)
    assert result["status"] == "passed"
    assert client.get("/api/v1/chat/sessions").status_code == 404
assert not any(m.startswith("safemeal.agent") for m in sys.modules)
assert "safemeal.config.settings" not in sys.modules
assert not hasattr(app.state.container, "_checkpointer")
print("standalone HTTP smoke passed")
"""
    env = dict(os.environ)
    for key in PlatformSettings.model_fields:
        env.pop(key, None)
    env.update(
        DATABASE_URL=f"sqlite:///{tmp_path / 'platform.sqlite'}",
        APP_ENV="test",
        SAFEMEAL_ENV_FILE=str(tmp_path / "absent.env"),
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not list(tmp_path.glob("*checkpoint*"))


def test_readiness_reports_missing_migrations(tmp_path):
    from fastapi.testclient import TestClient
    from safemeal.bootstrap.composition.platform_application import (
        create_platform_application,
    )
    from safemeal.infrastructure.persistence.database import dispose_engine

    dispose_engine()
    config = PlatformSettings(
        _env_file=None,
        DATABASE_URL=f"sqlite:///{tmp_path / 'empty.sqlite'}",
        APP_ENV="test",
        REDIS_RATE_LIMIT_URL=None,
        RECIPE_CACHE_URL=None,
        RECIPE_RANKING_REDIS_URL=None,
        BEHAVIOR_EVENT_REDIS_URL=None,
    )
    with TestClient(create_platform_application(config)) as client:
        assert client.get("/livez").status_code == 200
        response = client.get("/readyz")
        assert response.status_code == 503
        assert "recipes" in response.json()["checks"]["database"]["missing_tables"]


def test_platform_production_does_not_require_agent_credentials():
    config = PlatformSettings(
        _env_file=None,
        APP_ENV="production",
        DATABASE_URL="mysql+pymysql://demo:demo@mysql/recipe_db",
        CORS_ORIGINS="https://safemeal.example",
        AUTH_JWT_SECRET="x" * 40,
        BEHAVIOR_EVENT_REDIS_URL=None,
    )
    assert not hasattr(config, "LLM_API_KEY")
    assert not hasattr(config, "AGENT_CHECKPOINT_DATABASE_URL")


@pytest.mark.parametrize(
    "override",
    [
        {"DEBUG": True},
        {"DATABASE_URL": "sqlite:///:memory:"},
        {"CORS_ORIGINS": "*"},
        {"AUTH_JWT_SECRET": "short"},
        {"ENABLE_OIDC": True, "OIDC_ISSUER": None, "OIDC_AUDIENCE": None},
    ],
)
def test_platform_production_keeps_security_validation(override):
    fields = dict(
        APP_ENV="production",
        DATABASE_URL="mysql+pymysql://demo:demo@mysql/recipe_db",
        CORS_ORIGINS="https://safemeal.example",
        AUTH_JWT_SECRET="x" * 40,
        BEHAVIOR_EVENT_REDIS_URL=None,
    )
    fields.update(override)
    with pytest.raises(ValidationError):
        PlatformSettings(_env_file=None, **fields)


@pytest.mark.asyncio
async def test_platform_shutdown_closes_all_workers_and_resources(tmp_path):
    from safemeal.bootstrap.composition.platform_container import PlatformContainer
    from safemeal.infrastructure.persistence.database import dispose_engine

    dispose_engine()
    config = PlatformSettings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL=f"sqlite:///{tmp_path / 'shutdown.sqlite'}",
        BEHAVIOR_EVENT_REDIS_URL=None,
    )
    container = PlatformContainer(config)
    closed = []

    class Worker:
        def __init__(self, name, fail=False):
            self.name, self.fail = name, fail

        async def close(self):
            closed.append(self.name)
            if self.fail:
                raise RuntimeError("test shutdown failure")

    container._behavior_worker = Worker("behavior", fail=True)
    container._ranking_worker = Worker("ranking")
    container._resource_stack.callback(closed.append, "resources")
    await container.shutdown()
    assert closed == ["behavior", "ranking", "resources"]


@pytest.mark.asyncio
async def test_agent_shutdown_always_closes_shared_resources(monkeypatch):
    from safemeal.bootstrap.composition.application_container import (
        ApplicationContainer,
    )
    from safemeal.bootstrap.composition.platform_container import PlatformContainer

    closed = []

    async def shutdown(self):
        closed.append("platform")

    class Queue:
        async def close(self):
            raise RuntimeError("test queue close failure")

    monkeypatch.setattr(PlatformContainer, "shutdown", shutdown)
    container = ApplicationContainer.__new__(ApplicationContainer)
    container._document_knowledge_service = None
    container._language_model_gateway = None
    container._ingestion_queue = Queue()
    with pytest.raises(RuntimeError, match="queue close"):
        await container.shutdown()
    assert closed == ["platform"]
