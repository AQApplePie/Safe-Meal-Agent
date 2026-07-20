"""Restore a reviewed Milvus export into a fresh versioned collection."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Sequence

from pymilvus import connections, utility

from SafeMealAgent.back.config.settings import settings
from SafeMealAgent.back.infrastructure.retrieval.milvus.client import VectorStore
from SafeMealAgent.back.infrastructure.retrieval.milvus.migrate_collection import (
    CollectionMigrationError,
    embedding_values,
)


def _load_export(path: Path, expected_sha256: str) -> list[dict[str, object]]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise CollectionMigrationError("export must be an existing non-empty file")
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if digest != expected_sha256.strip().lower():
        raise CollectionMigrationError("export SHA-256 does not match")
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise CollectionMigrationError("export must contain a non-empty JSON array")
    rows = [dict(row) for row in payload if isinstance(row, dict)]
    if len(rows) != len(payload):
        raise CollectionMigrationError("every export row must be an object")
    required = {
        "id",
        "embedding",
        "content",
        "recipe_id",
        "name",
        "category",
        "difficulty",
    }
    if any(set(row) != required for row in rows):
        raise CollectionMigrationError(
            "export row schema does not match the reviewed legacy schema"
        )
    ids = [str(row["id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise CollectionMigrationError("export contains duplicate primary keys")
    return rows


def restore_collection(
    *,
    export_path: Path,
    export_sha256: str,
    target_name: str,
    alias_name: str,
) -> int:
    rows = _load_export(export_path, export_sha256)
    audit_alias = "safemeal_restore_audit"
    connections.connect(
        alias=audit_alias,
        host=settings.MILVUS_HOST,
        port=settings.MILVUS_PORT,
        timeout=settings.MILVUS_LOAD_TIMEOUT,
    )
    try:
        if utility.has_collection(target_name, using=audit_alias):
            raise CollectionMigrationError(f"target already exists: {target_name}")
        if utility.has_collection(alias_name, using=audit_alias):
            raise CollectionMigrationError(
                f"alias/collection already exists: {alias_name}"
            )
    finally:
        connections.disconnect(audit_alias)

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
        documents = [str(row["content"]) for row in rows]
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
        count = int(store.get_collection_stats()["document_count"])
    finally:
        store.close()
    if count != len(rows):
        raise CollectionMigrationError(
            f"restored count mismatch: expected={len(rows)}, actual={count}"
        )

    connections.connect(
        alias=audit_alias,
        host=settings.MILVUS_HOST,
        port=settings.MILVUS_PORT,
        timeout=settings.MILVUS_LOAD_TIMEOUT,
    )
    try:
        utility.create_alias(target_name, alias_name, using=audit_alias)
    finally:
        connections.disconnect(audit_alias)
    return count


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-file", required=True, type=Path)
    parser.add_argument("--export-sha256", required=True)
    parser.add_argument("--target", default=settings.MILVUS_COLLECTION_TARGET)
    parser.add_argument("--alias", default=settings.MILVUS_COLLECTION)
    args = parser.parse_args(argv)
    count = restore_collection(
        export_path=args.export_file,
        export_sha256=args.export_sha256,
        target_name=args.target,
        alias_name=args.alias,
    )
    print(f"Milvus restore passed: visible_entities={count} alias={args.alias}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
