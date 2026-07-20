"""Data-preserving migration from the legacy Milvus schema to schema v2."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from pymilvus import Collection, connections, utility

from SafeMealAgent.back.config.settings import settings
from SafeMealAgent.back.infrastructure.retrieval.milvus.client import (
    VectorStore,
    load_collection_with_hard_timeout,
)


class CollectionMigrationError(RuntimeError):
    """Raised when a collection migration cannot be proved lossless."""


def embedding_values(row: dict[str, object]) -> list[float]:
    """Validate an exported embedding before it reaches the target collection."""

    value = row.get("embedding")
    if not isinstance(value, list) or not value:
        raise CollectionMigrationError(
            "every export row must contain an embedding array"
        )
    if not all(isinstance(item, (int, float)) for item in value):
        raise CollectionMigrationError("embedding values must be numeric")
    return [float(item) for item in value]


def _export_legacy_rows(
    collection: Collection,
    *,
    timeout_seconds: float,
) -> list[dict[str, object]]:
    rows = collection.query(
        expr='id != ""',
        output_fields=[
            "id",
            "embedding",
            "content",
            "recipe_id",
            "name",
            "category",
            "difficulty",
        ],
        limit=16_384,
        timeout=timeout_seconds,
    )
    ids = [str(row.get("id") or "") for row in rows]
    if not rows:
        raise CollectionMigrationError(
            "legacy collection has physical entities but no query-visible records"
        )
    if any(not identifier for identifier in ids) or len(ids) != len(set(ids)):
        raise CollectionMigrationError(
            "legacy export contains blank or duplicate primary keys"
        )
    normalized_rows: list[dict[str, object]] = []
    for row in rows:
        normalized = dict(row)
        normalized["embedding"] = [float(value) for value in row["embedding"]]
        normalized_rows.append(normalized)
    return normalized_rows


def _write_export(path: Path, rows: list[dict[str, object]]) -> None:
    resolved = path.expanduser().resolve()
    if resolved.is_relative_to(Path.cwd().resolve()):
        raise CollectionMigrationError(
            "Milvus migration exports must be stored outside the repo"
        )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_suffix(resolved.suffix + ".partial")
    temporary.write_text(
        json.dumps(rows, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(resolved)


def migrate_collection(
    *,
    source_name: str,
    target_name: str,
    alias_name: str,
    export_path: Path,
) -> tuple[int, int, str]:
    if len({source_name, target_name, alias_name}) != 3:
        raise CollectionMigrationError(
            "source, target, and alias names must be distinct"
        )

    connection_alias = "safemeal_collection_migration"
    connections.connect(
        alias=connection_alias,
        host=settings.MILVUS_HOST,
        port=settings.MILVUS_PORT,
        timeout=settings.MILVUS_LOAD_TIMEOUT,
    )
    try:
        if not utility.has_collection(source_name, using=connection_alias):
            raise CollectionMigrationError(
                f"legacy collection does not exist: {source_name}"
            )
        if utility.has_collection(target_name, using=connection_alias):
            raise CollectionMigrationError(
                f"target collection already exists; inspect it before retrying: {target_name}"
            )

        source = Collection(source_name, using=connection_alias)
        source_fields = {field.name for field in source.schema.fields}
        expected_legacy_fields = {
            "id",
            "embedding",
            "content",
            "recipe_id",
            "name",
            "category",
            "difficulty",
        }
        if source_fields != expected_legacy_fields:
            raise CollectionMigrationError(
                "legacy collection schema drifted: "
                f"expected {sorted(expected_legacy_fields)}, found {sorted(source_fields)}"
            )

        load_collection_with_hard_timeout(
            host=settings.MILVUS_HOST,
            port=settings.MILVUS_PORT,
            collection_name=source_name,
            timeout_seconds=settings.MILVUS_LOAD_TIMEOUT,
        )
        physical_count = int(source.num_entities)
        rows = _export_legacy_rows(source, timeout_seconds=settings.MILVUS_LOAD_TIMEOUT)
        _write_export(export_path, rows)

        store = VectorStore(
            collection_name=target_name,
            host=settings.MILVUS_HOST,
            port=settings.MILVUS_PORT,
            dimension=settings.EMBEDDING_DIMENSION,
            index_type=settings.MILVUS_INDEX_TYPE,
            metric_type=settings.MILVUS_METRIC_TYPE,
            load_timeout_seconds=settings.MILVUS_LOAD_TIMEOUT,
        )
        try:
            ids = [str(row["id"]) for row in rows]
            embeddings = [embedding_values(row) for row in rows]
            documents = [str(row.get("content") or "") for row in rows]
            metadatas = []
            for row in rows:
                recipe_id = str(row.get("recipe_id") or row["id"])
                metadatas.append(
                    {
                        "document_id": f"legacy-recipe:{recipe_id}",
                        "recipe_id": recipe_id,
                        "name": str(row.get("name") or ""),
                        "category": str(row.get("category") or ""),
                        "difficulty": str(row.get("difficulty") or ""),
                    }
                )
            store.add_documents(ids, embeddings, documents, metadatas)
            target_count = int(store.get_collection_stats()["document_count"])
        finally:
            store.close()

        if target_count != len(rows):
            raise CollectionMigrationError(
                f"target count mismatch: expected={len(rows)}, actual={target_count}"
            )
        utility.create_alias(target_name, alias_name, using=connection_alias)
        return physical_count, target_count, alias_name
    finally:
        connections.disconnect(connection_alias)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=settings.MILVUS_LEGACY_COLLECTION)
    parser.add_argument("--target", default=settings.MILVUS_COLLECTION_TARGET)
    parser.add_argument("--alias", default=settings.MILVUS_COLLECTION)
    parser.add_argument("--export-file", required=True, type=Path)
    args = parser.parse_args(argv)
    physical_count, visible_count, alias = migrate_collection(
        source_name=args.source,
        target_name=args.target,
        alias_name=args.alias,
        export_path=args.export_file,
    )
    print(
        "Milvus migration passed: "
        f"legacy_physical={physical_count} migrated_visible={visible_count} alias={alias}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
