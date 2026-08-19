"""Persistent BM25 index backed by SQLite FTS5."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from threading import RLock

from safemeal.shared.types import JsonObject


_WORD = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff]")


def _tokens(text: str) -> list[str]:
    raw = _WORD.findall(text.casefold())
    chinese = [item for item in raw if len(item) == 1 and "\u3400" <= item <= "\u9fff"]
    words = [item for item in raw if item not in chinese]
    return [*words, *chinese, *(a + b for a, b in zip(chinese, chinese[1:]))]


class SqliteBm25Repository:
    """FTS5 BM25 retrieval with idempotent document replacement."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with self._connect() as connection:
            connection.execute(
                """CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_bm25 USING fts5(
                    chunk_id UNINDEXED, document_id UNINDEXED, content,
                    original_content UNINDEXED, metadata_json UNINDEXED
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def replace_document(
        self,
        document_id: str,
        ids: list[str],
        documents: list[str],
        metadatas: list[JsonObject],
    ) -> bool:
        if not (len(ids) == len(documents) == len(metadatas)):
            raise ValueError("BM25 documents, ids and metadata lengths must match")
        rows = [
            (
                chunk_id,
                document_id,
                " ".join(_tokens(content)),
                content,
                json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
            )
            for chunk_id, content, metadata in zip(ids, documents, metadatas)
        ]
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM knowledge_bm25 WHERE document_id=?", (document_id,)
            )
            connection.executemany(
                "INSERT INTO knowledge_bm25 VALUES (?, ?, ?, ?, ?)", rows
            )
        return True

    def search(
        self, query: str, top_k: int = 10, filter_by: JsonObject | None = None
    ) -> list[JsonObject]:
        terms = _tokens(query)
        if not terms:
            return []
        expression = " OR ".join(f'"{item}"' for item in dict.fromkeys(terms))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """SELECT chunk_id, document_id, original_content, metadata_json,
                          -bm25(knowledge_bm25) AS score
                   FROM knowledge_bm25 WHERE knowledge_bm25 MATCH ?
                   ORDER BY bm25(knowledge_bm25) LIMIT ?""",
                (expression, top_k),
            ).fetchall()
        results = [
            {
                "id": str(row["chunk_id"]),
                "document_id": str(row["document_id"]),
                "content": str(row["original_content"]),
                "metadata": json.loads(row["metadata_json"] or "{}"),
                "score": float(row["score"]),
            }
            for row in rows
        ]
        if filter_by and (tenant_id := filter_by.get("tenant_id")):
            results = [
                item
                for item in results
                if item["metadata"].get("tenant_id", "public") in {"public", tenant_id}
            ]
        return results

    def delete_documents(self, document_ids: list[str]) -> bool:
        with self._lock, self._connect() as connection:
            connection.executemany(
                "DELETE FROM knowledge_bm25 WHERE document_id=?",
                [(item,) for item in document_ids],
            )
        return True

    def close(self) -> None:
        return None


__all__ = ["SqliteBm25Repository"]
