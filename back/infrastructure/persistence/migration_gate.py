"""Safe database migration gate used by local and container startup."""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import AbstractSet, Sequence

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

from SafeMealAgent.back.config.settings import settings


APPLICATION_TABLES = frozenset(
    {"chat_sessions", "chat_messages", "user_memories", "answer_feedbacks"}
)
LEGACY_APPLICATION_TABLES = frozenset({"chat_history_snapshots"})
RECIPE_TABLES = frozenset(
    {
        "cuisines",
        "cooking_tools",
        "ingredients",
        "recipes",
        "recipe_steps",
        "recipe_ingredients",
        "step_tools",
    }
)


class DatabaseState(str, Enum):
    FRESH = "fresh"
    VERSIONED = "versioned"
    UNVERSIONED_APPLICATION_SCHEMA = "unversioned_application_schema"


@dataclass(frozen=True)
class GateResult:
    state: DatabaseState
    revision: str
    recipe_count: int


class MigrationGateError(RuntimeError):
    """Raised when automatic migration cannot be proved safe."""


def _verify_backup(backup_path: str, expected_sha256: str) -> Path:
    path = Path(backup_path).expanduser().resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise MigrationGateError("adoption backup must be an existing non-empty file")
    normalized_sha = expected_sha256.strip().lower()
    if len(normalized_sha) != 64 or any(
        character not in "0123456789abcdef" for character in normalized_sha
    ):
        raise MigrationGateError(
            "backup SHA-256 must contain exactly 64 hexadecimal characters"
        )
    digest = hashlib.sha256()
    with path.open("rb") as backup_file:
        for chunk in iter(lambda: backup_file.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != normalized_sha:
        raise MigrationGateError(
            "adoption backup SHA-256 does not match the supplied file"
        )
    return path


def classify_database_state(table_names: AbstractSet[str]) -> DatabaseState:
    """Classify a schema without changing it."""

    if "alembic_version" in table_names:
        return DatabaseState.VERSIONED
    if table_names & (APPLICATION_TABLES | LEGACY_APPLICATION_TABLES):
        return DatabaseState.UNVERSIONED_APPLICATION_SCHEMA
    return DatabaseState.FRESH


def _alembic_config() -> Config:
    return Config("alembic.ini")


def _expected_head(config: Config) -> str:
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise MigrationGateError(f"expected one Alembic head, found {len(heads)}")
    return heads[0]


def _schema_snapshot() -> tuple[set[str], str | None, int]:
    connect_args = {}
    if settings.DATABASE_URL.lower().startswith("mysql"):
        connect_args["connect_timeout"] = settings.DB_CONNECT_TIMEOUT
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        poolclass=NullPool,
        connect_args=connect_args,
        future=True,
    )
    try:
        with engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
            revision = MigrationContext.configure(connection).get_current_revision()
            recipe_count = 0
            if "recipes" in tables:
                recipe_count = int(
                    connection.execute(
                        text("SELECT COUNT(*) FROM recipes")
                    ).scalar_one()
                )
            return tables, revision, recipe_count
    finally:
        engine.dispose()


def verify_database() -> GateResult:
    """Verify revision, required tables, and recipe seed data without mutation."""

    config = _alembic_config()
    expected_head = _expected_head(config)
    tables, revision, recipe_count = _schema_snapshot()
    state = classify_database_state(tables)

    if state is DatabaseState.UNVERSIONED_APPLICATION_SCHEMA:
        raise MigrationGateError(
            "existing application tables have no Alembic revision; refusing to stamp or migrate "
            "automatically. Back up the database and complete the documented adoption procedure."
        )
    if revision != expected_head:
        raise MigrationGateError(
            f"database revision is {revision or 'missing'}, expected {expected_head}"
        )

    missing_tables = sorted((APPLICATION_TABLES | RECIPE_TABLES) - tables)
    if missing_tables:
        raise MigrationGateError(
            "required tables are missing: " + ", ".join(missing_tables)
        )
    if recipe_count < 1:
        raise MigrationGateError(
            "recipes table is empty; seed or migrate recipe data before startup"
        )

    return GateResult(state=state, revision=expected_head, recipe_count=recipe_count)


def upgrade_database() -> GateResult:
    """Upgrade only a fresh schema or an already versioned schema, then verify it."""

    tables, _, _ = _schema_snapshot()
    state = classify_database_state(tables)
    if state is DatabaseState.UNVERSIONED_APPLICATION_SCHEMA:
        raise MigrationGateError(
            "existing application tables have no Alembic revision; refusing automatic upgrade. "
            "Never use `alembic stamp head` as a substitute for schema adoption."
        )

    command.upgrade(_alembic_config(), "head")
    return verify_database()


def adopt_database(*, backup_path: str, backup_sha256: str) -> GateResult:
    """Adopt only the reviewed unversioned schema after proving a backup exists.

    The initial Alembic revision performs the schema assertions before issuing
    DDL.  This command deliberately remains separate from automatic startup so
    an unversioned production volume can never be adopted by a routine deploy.
    """

    _verify_backup(backup_path, backup_sha256)
    tables, _, recipe_count = _schema_snapshot()
    if (
        classify_database_state(tables)
        is not DatabaseState.UNVERSIONED_APPLICATION_SCHEMA
    ):
        raise MigrationGateError("adopt requires an unversioned application schema")
    missing_recipe_tables = sorted(RECIPE_TABLES - tables)
    if missing_recipe_tables:
        raise MigrationGateError(
            "cannot adopt because recipe tables are missing: "
            + ", ".join(missing_recipe_tables)
        )
    if recipe_count < 1:
        raise MigrationGateError("cannot adopt an empty recipes table")

    command.upgrade(_alembic_config(), "head")
    return verify_database()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("upgrade", "verify", "adopt"))
    parser.add_argument(
        "--backup-file",
        help="Out-of-repository database backup required by the adopt action",
    )
    parser.add_argument(
        "--backup-sha256",
        help="Expected SHA-256 for --backup-file",
    )
    args = parser.parse_args(argv)
    try:
        if args.action == "upgrade":
            result = upgrade_database()
        elif args.action == "verify":
            result = verify_database()
        else:
            if not args.backup_file or not args.backup_sha256:
                raise MigrationGateError(
                    "adopt requires --backup-file and --backup-sha256"
                )
            result = adopt_database(
                backup_path=args.backup_file,
                backup_sha256=args.backup_sha256,
            )
    except MigrationGateError as exc:
        parser.exit(2, f"database gate failed: {exc}\n")
    print(
        f"database gate passed: state={result.state.value} "
        f"revision={result.revision} recipes={result.recipe_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
